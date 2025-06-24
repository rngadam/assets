import argparse
import os
import sys
import hashlib
import subprocess
import re
from pathlib import Path
import html
import json

# Define constants for output directories and index file location
BASE_OUTPUT_DIR = Path("processed_media")
DESCRIPTION_DIR = BASE_OUTPUT_DIR / "descriptions"
IMAGE_DIR = BASE_OUTPUT_DIR / "images"
VIDEO_DIR = BASE_OUTPUT_DIR / "videos"
HTML_DIR = BASE_OUTPUT_DIR / "html"
INDEX_FILE_PATH = Path("index.json") # Root level index.json

# Define processing step keywords
STEP_GEMINI_DESCRIPTION = "gemini_description"
STEP_IMAGE_CONVERSION = "image_conversion"
STEP_HTML_GENERATION = "html_generation"
STEP_VIDEO_CONVERSION = "video_conversion"
# BASE_NAME_FLAG_PREFIX = "base_name:" # No longer needed

# Ensure output directories exist (idempotent)
DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)
# FLAG_DIR.mkdir(parents=True, exist_ok=True) # No longer needed

def log_message(message, level="INFO"):
    print(f"[{level}] {message}", file=sys.stderr if level == "ERROR" else sys.stdout)

# --- Start of new JSON handling functions ---
def load_index_data(index_path: Path) -> list[dict]:
    """Loads index.json if it exists, returns an empty list otherwise."""
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                log_message(f"Warning: index.json content is not a list. Starting fresh.", level="WARNING")
                return []
        except json.JSONDecodeError:
            log_message(f"Error decoding index.json. Starting fresh.", level="ERROR")
            return []
    return []

def save_index_data(index_path: Path, data: list[dict]):
    """Saves the data to index.json."""
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        log_message(f"Saved data to {index_path}")
    except IOError as e:
        log_message(f"Error saving index data to {index_path}: {e}", level="ERROR")


def find_asset_in_index(index_data: list[dict], file_hash: str) -> dict | None:
    """Finds an asset by its source hash."""
    for asset in index_data:
        if asset.get("source_hash") == file_hash:
            return asset
    return None

def update_asset_in_index(index_data: list[dict], asset_data: dict) -> list[dict]:
    """Updates an existing asset or adds a new one. Returns the modified index_data."""
    source_hash = asset_data.get("source_hash")
    if not source_hash:
        log_message("Error: Asset data must have a 'source_hash' to be updated in index.", level="ERROR")
        return index_data # Return original data if no hash

    for i, existing_asset in enumerate(index_data):
        if existing_asset.get("source_hash") == source_hash:
            index_data[i] = asset_data
            return index_data
    # If not found, add as new asset
    index_data.append(asset_data)
    return index_data

# --- End of new JSON handling functions ---


def main():
    parser = argparse.ArgumentParser(description="Process a single media file.")
    parser.add_argument("--input-file", required=True, help="Path to the input media file.")
    parser.add_argument("--file-hash", required=True, help="MD5 hash of the input file.")
    parser.add_argument("--gemini-api-key", required=True, help="Gemini API Key.")
    parser.add_argument("--github-repository", required=True, help="GitHub repository (e.g., owner/repo).")
    parser.add_argument("--github-ref-for-raw-url", required=True, help="GitHub ref for raw content URLs (e.g., refs/heads/main or a SHA).")

    args = parser.parse_args()

    log_message(f"Starting processing for file: {args.input_file} (hash: {args.file_hash})")

    # Load existing index data
    index_data = load_index_data(INDEX_FILE_PATH)
    current_asset_data = find_asset_in_index(index_data, args.file_hash)

    if current_asset_data is None:
        log_message(f"No existing entry found for hash {args.file_hash}. Creating new entry.")
        current_asset_data = {
            "source_file_path": args.input_file,
            "source_hash": args.file_hash,
            "base_name": None,
            "description_markdown_path": None,
            "processed_steps": [],
            "outputs": {
                "type": None, # Will be 'image' or 'video'
                "html_page_path": None,
                "image_files": [],
                "video_files": []
            },
            "raw_content_url_prefix": f"https://raw.githubusercontent.com/{args.github_repository}/{args.github_ref_for_raw_url}/"
        }
    else:
        log_message(f"Found existing entry for hash {args.file_hash}.")
        # Ensure essential keys exist if loading an older or incomplete entry
        current_asset_data.setdefault("processed_steps", [])
        current_asset_data.setdefault("outputs", {
            "type": None, "html_page_path": None, "image_files": [], "video_files": []
        })
        current_asset_data["raw_content_url_prefix"] = f"https://raw.githubusercontent.com/{args.github_repository}/{args.github_ref_for_raw_url}/" # Update if needed
        current_asset_data["source_file_path"] = args.input_file # Update in case it changed (though hash should be stable)


    processed_steps = set(current_asset_data.get("processed_steps", []))
    current_base_name = current_asset_data.get("base_name")
    full_description_content = ""


    # ---- Gemini Description Step ----
    if STEP_GEMINI_DESCRIPTION not in processed_steps:
        log_message(f"Running Gemini Description step for {args.input_file}...")
        gemini_script_path = Path(__file__).parent / "get_gemini_description.py"

        cmd = [
            sys.executable, # Path to current python interpreter
            str(gemini_script_path),
            args.gemini_api_key,
            args.input_file,
            str(DESCRIPTION_DIR)
        ]

        try:
            # It's good practice to make file paths absolute for subprocesses if there's any ambiguity
            # For input_file, it's passed from YAML so it should be relative to GITHUB_WORKSPACE
            # For gemini_script_path and DESCRIPTION_DIR, we've made them absolute or relative to script loc.

            log_message(f"Executing command: {' '.join(cmd[:2])} <API_KEY> {' '.join(cmd[3:])}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=Path.cwd()) # Use cwd for context

            if result.returncode == 0:
                gemini_output_base_name = result.stdout.strip()
                if "error-" in gemini_output_base_name.lower() or not gemini_output_base_name:
                    log_message(f"Gemini script indicated an error or returned empty: {gemini_output_base_name}", level="ERROR")
                    # Use a generic base_name based on hash if Gemini fails to produce a valid one
                    current_base_name = f"generic-media-{args.file_hash[:8]}"
                    # The get_gemini_description.py script itself creates an error .md file.
                    # We won't record base_name to index on error, to allow retry of Gemini step.
                else:
                    log_message(f"Gemini script succeeded. Base name: {gemini_output_base_name}")
                    current_base_name = gemini_output_base_name
                    current_asset_data["base_name"] = current_base_name
                    # The get_gemini_description.py script creates the .md file.
                    # We construct the expected path to store it in the index.
                    current_asset_data["description_markdown_path"] = str(DESCRIPTION_DIR / f"{current_base_name}.md")
                    processed_steps.add(STEP_GEMINI_DESCRIPTION)
                    current_asset_data["processed_steps"] = sorted(list(processed_steps))
                    log_message(f"Updated asset data with base_name '{current_base_name}' and step {STEP_GEMINI_DESCRIPTION}")
            else:
                log_message(f"Gemini script failed with return code {result.returncode}.", level="ERROR")
                log_message(f"Stderr: {result.stderr.strip()}", level="ERROR")
                log_message(f"Stdout: {result.stdout.strip()}", level="ERROR")
                current_base_name = f"generic-media-script-failed-{args.file_hash[:8]}"
                # Do not record step or base_name to allow retry
        except FileNotFoundError:
            log_message(f"Error: The script {gemini_script_path} was not found.", level="ERROR")
            current_base_name = f"generic-media-script-missing-{args.file_hash[:8]}"
        except Exception as e:
            log_message(f"An exception occurred while running Gemini script: {e}", level="ERROR")
            current_base_name = f"generic-media-exception-{args.file_hash[:8]}"

    else:
        log_message(f"Skipping Gemini Description step for {args.input_file} (already processed).")
        if not current_base_name: # Should be current_asset_data["base_name"]
            log_message("Error: Gemini description was marked as processed, but base_name is missing in index data.", level="ERROR")
            # Fallback if base_name is somehow missing after being processed.
            current_base_name = f"generic-recovery-{args.file_hash[:8]}"
            current_asset_data["base_name"] = current_base_name # Attempt to fix current_asset_data

    # Load description content if base_name is available and description path is set
    if current_base_name and current_asset_data.get("description_markdown_path"):
        description_md_file = Path(current_asset_data["description_markdown_path"])
        if description_md_file.exists():
            try:
                with open(description_md_file, "r", encoding="utf-8") as f_desc:
                    full_description_content = f_desc.read()
                log_message(f"Loaded description from {description_md_file}")
            except IOError as e:
                log_message(f"Error reading description file {description_md_file}: {e}", level="ERROR")
                full_description_content = "Error reading description file."
        else:
            log_message(f"Warning: Description file {description_md_file} not found, even after Gemini step (or skip).", level="WARNING")
            full_description_content = "Description file was expected but not found."
    elif current_base_name and not current_asset_data.get("description_markdown_path"):
        log_message(f"Warning: base_name '{current_base_name}' exists, but description_markdown_path is not set in index.", level="WARNING")
        # Try to reconstruct path if needed, or handle as missing
        # For now, treat as missing content.
        full_description_content = "Description path missing in index."
    elif not current_base_name:
        log_message("Critical Error: base_name is not set after Gemini step. Cannot proceed with further file-specific processing.", level="ERROR")
        # Update index before exiting due to critical error
        index_data = update_asset_in_index(index_data, current_asset_data)
        save_index_data(INDEX_FILE_PATH, index_data)
        sys.exit(1) # Exit if no base_name, as it's crucial.

    log_message(f"Using base_name: '{current_base_name}' for outputs.")


    # ---- Determine File Type ----
    file_extension = Path(args.input_file).suffix.lower()
    is_image = file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    is_video = file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv']

    # Set asset type in index
    if is_image:
        current_asset_data["outputs"]["type"] = "image"
    elif is_video:
        current_asset_data["outputs"]["type"] = "video"
    else:
        current_asset_data["outputs"]["type"] = "unknown"


    if not current_base_name and (is_image or is_video): # This check is somewhat redundant due to earlier exit
        log_message("Critical: base_name is not set, but processing is required for image/video. Aborting this file.", level="ERROR")
        index_data = update_asset_in_index(index_data, current_asset_data)
        save_index_data(INDEX_FILE_PATH, index_data)
        sys.exit(1)

    elif is_image:
        # ---- Image Conversion Step ----
        if STEP_IMAGE_CONVERSION not in processed_steps:
            log_message(f"Running Image Conversion step for {args.input_file}...")
            widths = [1920, 1280, 640]
            conversion_ok = True
            current_asset_data["outputs"]["image_files"] = [] # Clear previous attempts if any

            for width in widths:
                try:
                    # JPEG
                    jpg_filename = f"{current_base_name}-{width}w.jpg"
                    output_jpg_abs_path = IMAGE_DIR / jpg_filename
                    cmd_convert_jpg = [
                        "convert", args.input_file, "-resize", f"{width}x>", "-quality", "85", str(output_jpg_abs_path)
                    ]
                    subprocess.run(cmd_convert_jpg, check=True, capture_output=True)
                    cmd_exif_jpg = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_jpg_abs_path)
                    ]
                    subprocess.run(cmd_exif_jpg, check=False, capture_output=True)
                    if (output_jpg_abs_path.parent / f"{output_jpg_abs_path.name}_original").exists():
                        (output_jpg_abs_path.parent / f"{output_jpg_abs_path.name}_original").unlink()
                    current_asset_data["outputs"]["image_files"].append({
                        "format": "jpg", "width": width, "path": str(Path(IMAGE_DIR.name) / jpg_filename) # Store path relative to BASE_OUTPUT_DIR
                    })

                    # WebP
                    webp_filename = f"{current_base_name}-{width}w.webp"
                    output_webp_abs_path = IMAGE_DIR / webp_filename
                    cmd_convert_webp = [
                        "convert", args.input_file, "-resize", f"{width}x>", "-quality", "80", str(output_webp_abs_path)
                    ]
                    subprocess.run(cmd_convert_webp, check=True, capture_output=True)
                    cmd_exif_webp = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_webp_abs_path)
                    ]
                    subprocess.run(cmd_exif_webp, check=False, capture_output=True)
                    if (output_webp_abs_path.parent / f"{output_webp_abs_path.name}_original").exists():
                        (output_webp_abs_path.parent / f"{output_webp_abs_path.name}_original").unlink()
                    current_asset_data["outputs"]["image_files"].append({
                        "format": "webp", "width": width, "path": str(Path(IMAGE_DIR.name) / webp_filename) # Store path relative to BASE_OUTPUT_DIR
                    })
                    log_message(f"Successfully converted to {width}w (JPG/WebP) for {current_base_name}")

                except subprocess.CalledProcessError as e:
                    log_message(f"Error during image conversion for width {width}: {e.stderr.decode() if e.stderr else e.stdout.decode()}", level="ERROR")
                    conversion_ok = False
                    break
                except Exception as e_gen:
                    log_message(f"Generic error during image conversion for width {width}: {e_gen}", level="ERROR")
                    conversion_ok = False
                    break

            if conversion_ok:
                processed_steps.add(STEP_IMAGE_CONVERSION)
                current_asset_data["processed_steps"] = sorted(list(processed_steps))
                log_message(f"Image conversion successful. Updated asset data with step {STEP_IMAGE_CONVERSION}")
            else:
                log_message("Image conversion failed. Not marking step as complete.", level="ERROR")
        else:
            log_message(f"Skipping Image Conversion for {args.input_file} (already processed).")

        # ---- HTML Generation Step ----
        expected_image_file_check = IMAGE_DIR / f"{current_base_name}-640w.jpg" # Check for one expected file
        if (STEP_IMAGE_CONVERSION in processed_steps or expected_image_file_check.exists()):
            if STEP_HTML_GENERATION not in processed_steps:
                log_message(f"Running HTML Generation for {args.input_file}...")
                # Use raw_content_url_prefix from current_asset_data
                raw_content_url_prefix = current_asset_data["raw_content_url_prefix"]
                html_filename = f"{current_base_name}.html"
                output_html_file_abs = HTML_DIR / html_filename # Absolute path for writing
                # output_html_file_rel = str(HTML_DIR.name / html_filename) # This line caused a TypeError and was unused. Removing.

                widths = [1920, 1280, 640]
                webp_srcset_parts = []
                jpeg_srcset_parts = []

                # Construct srcset using relative paths from index and raw_content_url_prefix
                # This assumes image_files in index are correctly populated with relative paths
                for img_output in current_asset_data["outputs"].get("image_files", []):
                    # img_output["path"] should be like "images/basename-1280w.jpg"
                    # So, raw_content_url_prefix + "processed_media/" + img_output["path"]
                    # No, BASE_OUTPUT_DIR.name is "processed_media"
                    # So, raw_content_url_prefix + BASE_OUTPUT_DIR.name + "/" + img_output["path"]
                    # Correct: raw_content_url_prefix + img_output["path"] if path includes "processed_media/images/..."
                    # The stored path is currently "images/basename-1280w.jpg".
                    # So it should be raw_content_url_prefix + "processed_media/" + img_output["path"]

                    # The path stored in image_files is relative to BASE_OUTPUT_DIR ("processed_media")
                    # e.g. images/my-image-1280w.jpg
                    # So the full URL should be raw_content_url_prefix + "processed_media/" + stored_path

                    # Let's re-evaluate how paths are stored in `image_files`.
                    # Plan says: "Path to the generated image file."
                    # For consistency, let's make it relative to repo root: "processed_media/images/..."
                    # The current code stores it relative to IMAGE_DIR.name: "images/..."
                    # This needs to be fixed when populating `image_files`.
                    # For now, let's assume the paths in current_asset_data["outputs"]["image_files"]
                    # are paths relative to `processed_media/` directory.
                    # Example: if img_output["path"] is "images/crane-statue-garden-flowers-building-1280w.webp"
                    # then full URL is raw_content_url_prefix + "processed_media/" + img_output["path"]

                    # The current code for populating image_files:
                    # str(IMAGE_DIR.name / jpg_filename) -> "images/base-1280w.jpg"
                    # This is relative to `processed_media`.
                    # So, the URL construction should be:
                    # image_url = f"{raw_content_url_prefix}{BASE_OUTPUT_DIR.name}/{img_output['path']}"

                    image_url = f"{raw_content_url_prefix}{BASE_OUTPUT_DIR.name}/{img_output['path']}"

                    if img_output["format"] == "webp":
                        webp_srcset_parts.append(f"{image_url} {img_output['width']}w")
                    elif img_output["format"] == "jpg":
                        jpeg_srcset_parts.append(f"{image_url} {img_output['width']}w")

                webp_srcset = ", ".join(webp_srcset_parts)
                jpeg_srcset = ", ".join(jpeg_srcset_parts)

                # Fallback image: find the 640w JPG
                fallback_img_src = ""
                for img_output in current_asset_data["outputs"].get("image_files", []):
                    if img_output["format"] == "jpg" and img_output["width"] == 640:
                        fallback_img_src = f"{raw_content_url_prefix}{BASE_OUTPUT_DIR.name}/{img_output['path']}"
                        break
                if not fallback_img_src and jpeg_srcset_parts: # Fallback to any jpg if 640 not found
                     fallback_img_src = jpeg_srcset_parts[0].split(" ")[0]


                escaped_alt_text = html.escape(full_description_content)
                template_path = Path(__file__).parent / "templates" / "media_template.html"
                try:
                    with open(template_path, "r", encoding="utf-8") as f_template:
                        html_template_content = f_template.read()

                    html_content = html_template_content.replace("{{TITLE}}", current_base_name)
                    html_content = html_content.replace("{{BASE_NAME}}", current_base_name)
                    html_content = html_content.replace("{{WEBP_SRCSET}}", webp_srcset)
                    html_content = html_content.replace("{{JPEG_SRCSET}}", jpeg_srcset)
                    html_content = html_content.replace("{{FALLBACK_IMG_SRC}}", fallback_img_src)
                    html_content = html_content.replace("{{ALT_TEXT}}", escaped_alt_text)

                    with open(output_html_file_abs, "w", encoding="utf-8") as f_html:
                        f_html.write(html_content)
                    log_message(f"Generated HTML file: {output_html_file_abs}")
                    current_asset_data["outputs"]["html_page_path"] = str(BASE_OUTPUT_DIR.name / HTML_DIR.name / html_filename) # Store relative to repo root
                    processed_steps.add(STEP_HTML_GENERATION)
                    current_asset_data["processed_steps"] = sorted(list(processed_steps))
                except FileNotFoundError:
                    log_message(f"Error: HTML template file not found at {template_path}", level="ERROR")
                except IOError as e:
                    log_message(f"Error reading HTML template or writing HTML file {output_html_file_abs}: {e}", level="ERROR")
            else:
                log_message(f"Skipping HTML Generation for {args.input_file} (already processed).")
        else:
            log_message(f"Skipping HTML Generation for {args.input_file} because image conversion step is not flagged as complete or expected image files are missing.")

    elif is_video:
        if STEP_VIDEO_CONVERSION not in processed_steps:
            log_message(f"Running Video Conversion step for {args.input_file}...")
            heights = [1080, 720]
            conversion_ok = True
            current_asset_data["outputs"]["video_files"] = [] # Clear previous attempts

            for height in heights:
                try:
                    # MP4 (H.264)
                    mp4_filename = f"{current_base_name}-{height}p.mp4"
                    output_mp4_abs_path = VIDEO_DIR / mp4_filename
                    cmd_ffmpeg_mp4 = [
                        "ffmpeg", "-i", args.input_file,
                        "-vf", f"scale=-2:min(ih\\,{height})",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        str(output_mp4_abs_path), "-y"
                    ]
                    subprocess.run(cmd_ffmpeg_mp4, check=True, capture_output=True)
                    cmd_exif_mp4 = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_mp4_abs_path)
                    ]
                    subprocess.run(cmd_exif_mp4, check=False, capture_output=True)
                    if (output_mp4_abs_path.parent / f"{output_mp4_abs_path.name}_original").exists():
                        (output_mp4_abs_path.parent / f"{output_mp4_abs_path.name}_original").unlink()
                    current_asset_data["outputs"]["video_files"].append({
                        "format": "mp4", "height": height, "path": str(BASE_OUTPUT_DIR.name / VIDEO_DIR.name / mp4_filename) # Relative to repo root
                    })

                    # WebM (VP9)
                    webm_filename = f"{current_base_name}-{height}p.webm"
                    output_webm_abs_path = VIDEO_DIR / webm_filename
                    cmd_ffmpeg_webm = [
                        "ffmpeg", "-i", args.input_file,
                        "-vf", f"scale=-2:min(ih\\,{height})",
                        "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                        "-c:a", "libopus", "-b:a", "128k",
                        str(output_webm_abs_path), "-y"
                    ]
                    subprocess.run(cmd_ffmpeg_webm, check=True, capture_output=True)
                    cmd_exif_webm = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_webm_abs_path)
                    ]
                    subprocess.run(cmd_exif_webm, check=False, capture_output=True)
                    if (output_webm_abs_path.parent / f"{output_webm_abs_path.name}_original").exists():
                        (output_webm_abs_path.parent / f"{output_webm_abs_path.name}_original").unlink()
                    current_asset_data["outputs"]["video_files"].append({
                        "format": "webm", "height": height, "path": str(BASE_OUTPUT_DIR.name / VIDEO_DIR.name / webm_filename) # Relative to repo root
                    })
                    log_message(f"Successfully converted video to {height}p (MP4/WebM) for {current_base_name}")

                except subprocess.CalledProcessError as e:
                    log_message(f"Error during video conversion for height {height}: {e.stderr.decode() if e.stderr else e.stdout.decode()}", level="ERROR")
                    conversion_ok = False
                    break
                except Exception as e_gen:
                    log_message(f"Generic error during video conversion for height {height}: {e_gen}", level="ERROR")
                    conversion_ok = False
                    break

            if conversion_ok:
                processed_steps.add(STEP_VIDEO_CONVERSION)
                current_asset_data["processed_steps"] = sorted(list(processed_steps))
                log_message(f"Video conversion successful. Updated asset data with step {STEP_VIDEO_CONVERSION}")
            else:
                log_message("Video conversion failed. Not marking step as complete.", level="ERROR")
        else:
            log_message(f"Skipping Video Conversion for {args.input_file} (already processed).")
    else:
        log_message(f"File {args.input_file} is not a recognized image or video type for media processing. Extension: {file_extension}")

    # Save updated index data for this asset
    index_data = update_asset_in_index(index_data, current_asset_data)
    save_index_data(INDEX_FILE_PATH, index_data)

    log_message(f"Finished processing for file: {args.input_file}")

# Removed old flag file functions:
# read_flag_file, record_step_in_flag_file, record_base_name_in_flag_file

if __name__ == "__main__":
    main()
