import argparse
import os
import sys
import hashlib
import subprocess
import re
from pathlib import Path

# Define constants for output directories and flag file location
BASE_OUTPUT_DIR = Path("processed_media")
DESCRIPTION_DIR = BASE_OUTPUT_DIR / "descriptions"
IMAGE_DIR = BASE_OUTPUT_DIR / "images"
VIDEO_DIR = BASE_OUTPUT_DIR / "videos"
HTML_DIR = BASE_OUTPUT_DIR / "html"
FLAG_DIR = Path("processed_flags")

# Define processing step keywords
STEP_GEMINI_DESCRIPTION = "gemini_description"
STEP_IMAGE_CONVERSION = "image_conversion"
STEP_HTML_GENERATION = "html_generation"
STEP_VIDEO_CONVERSION = "video_conversion"
BASE_NAME_FLAG_PREFIX = "base_name:"

# Ensure output directories exist (idempotent)
DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)
FLAG_DIR.mkdir(parents=True, exist_ok=True)

def log_message(message, level="INFO"):
    print(f"[{level}] {message}", file=sys.stderr if level == "ERROR" else sys.stdout)

def main():
    parser = argparse.ArgumentParser(description="Process a single media file.")
    parser.add_argument("--input-file", required=True, help="Path to the input media file.")
    parser.add_argument("--file-hash", required=True, help="MD5 hash of the input file.")
    parser.add_argument("--gemini-api-key", required=True, help="Gemini API Key.")
    parser.add_argument("--github-repository", required=True, help="GitHub repository (e.g., owner/repo).")
    parser.add_argument("--github-ref-for-raw-url", required=True, help="GitHub ref for raw content URLs (e.g., refs/heads/main or a SHA).")

    args = parser.parse_args()

    log_message(f"Starting processing for file: {args.input_file} (hash: {args.file_hash})")

    # Further logic will be added here in subsequent steps.
    # For now, just demonstrate argument parsing.
    log_message(f"Input File: {args.input_file}")
    log_message(f"File Hash: {args.file_hash}")
    log_message(f"GitHub Repository: {args.github_repository}")
    log_message(f"GitHub Ref for Raw URL: {args.github_ref_for_raw_url}")
    # Gemini API key is sensitive, so avoid logging it directly unless for specific debug and ensure it's not committed.
    # log_message(f"Gemini API Key: {'*' * len(args.gemini_api_key) if args.gemini_api_key else 'Not provided'}")


    # Placeholder for where the processing logic will go
    flag_file_path = FLAG_DIR / args.file_hash

    processed_steps, base_name_from_flag = read_flag_file(flag_file_path)
    log_message(f"Read from flag file: Steps={processed_steps}, BaseName='{base_name_from_flag}'")

    # Example of how to record a step (actual recording will happen after each step)
    current_base_name = base_name_from_flag
    full_description_content = ""


    # ---- Gemini Description Step ----
    if STEP_GEMINI_DESCRIPTION not in processed_steps:
        log_message(f"Running Gemini Description step for {args.input_file}...")
        # Path to the get_gemini_description.py script, assuming it's in the same directory
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
                    # We won't record base_name to flag on error, to allow retry of Gemini step.
                else:
                    log_message(f"Gemini script succeeded. Base name: {gemini_output_base_name}")
                    current_base_name = gemini_output_base_name
                    record_step_in_flag_file(flag_file_path, STEP_GEMINI_DESCRIPTION)
                    record_base_name_in_flag_file(flag_file_path, current_base_name)
                    processed_steps.add(STEP_GEMINI_DESCRIPTION)
                    log_message(f"Recorded {STEP_GEMINI_DESCRIPTION} and base_name '{current_base_name}' to {flag_file_path}")
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
        if not current_base_name:
            log_message("Error: Gemini description was flagged as done, but base_name could not be retrieved from flag file. This indicates a potential issue with flag file integrity or initial population.", level="ERROR")
            # Fallback, though this situation implies a problem.
            current_base_name = f"generic-recovery-{args.file_hash[:8]}"

    # Load description content if base_name is available
    if current_base_name:
        description_md_file = DESCRIPTION_DIR / f"{current_base_name}.md"
        if description_md_file.exists():
            with open(description_md_file, "r", encoding="utf-8") as f_desc:
                full_description_content = f_desc.read()
            log_message(f"Loaded description from {description_md_file}")
        else:
            log_message(f"Warning: Description file {description_md_file} not found, even after Gemini step (or skip).", level="WARNING")
            full_description_content = "Description file was expected but not found."
    else: # This case should ideally be handled by fallbacks above to always have some current_base_name
        log_message("Critical Error: base_name is not set after Gemini step. Cannot proceed with further file-specific processing.", level="ERROR")
        # Depending on desired strictness, could exit here: sys.exit(1)
        # For now, we'll let it continue and subsequent steps might fail or use a very generic name if they don't also check current_base_name

    log_message(f"Using base_name: '{current_base_name}' for outputs.")
    # log_message(f"Using description: '{full_description_content[:100]}...'")


    # ---- Determine File Type ----
    file_extension = Path(args.input_file).suffix.lower()
    is_image = file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    is_video = file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv']

    if not current_base_name and (is_image or is_video):
        log_message("Critical: base_name is not set, but processing is required for image/video. Aborting this file.", level="ERROR")
        # In a real scenario, might want to sys.exit(1) or raise an exception
        # For now, we'll just skip further processing for this file.
    elif is_image:
        # ---- Image Conversion Step ----
        if STEP_IMAGE_CONVERSION not in processed_steps:
            log_message(f"Running Image Conversion step for {args.input_file}...")
            widths = [1920, 1280, 640]
            conversion_ok = True
            for width in widths:
                try:
                    # JPEG
                    output_jpg_rel_path = f"images/{current_base_name}-{width}w.jpg"
                    output_jpg_abs_path = IMAGE_DIR / f"{current_base_name}-{width}w.jpg"
                    cmd_convert_jpg = [
                        "convert", args.input_file, "-resize", f"{width}x>", "-quality", "85", str(output_jpg_abs_path)
                    ]
                    subprocess.run(cmd_convert_jpg, check=True, capture_output=True)
                    cmd_exif_jpg = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_jpg_abs_path)
                    ]
                    subprocess.run(cmd_exif_jpg, check=False, capture_output=True) # check=False as exiftool can have non-fatal warnings
                    if (output_jpg_abs_path.parent / f"{output_jpg_abs_path.name}_original").exists():
                        (output_jpg_abs_path.parent / f"{output_jpg_abs_path.name}_original").unlink()

                    # WebP
                    output_webp_rel_path = f"images/{current_base_name}-{width}w.webp"
                    output_webp_abs_path = IMAGE_DIR / f"{current_base_name}-{width}w.webp"
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

                    log_message(f"Successfully converted to {width}w (JPG/WebP) for {current_base_name}")

                except subprocess.CalledProcessError as e:
                    log_message(f"Error during image conversion for width {width}: {e.stderr.decode() if e.stderr else e.stdout.decode()}", level="ERROR")
                    conversion_ok = False
                    break # Stop processing further widths for this image
                except Exception as e_gen:
                    log_message(f"Generic error during image conversion for width {width}: {e_gen}", level="ERROR")
                    conversion_ok = False
                    break

            if conversion_ok:
                record_step_in_flag_file(flag_file_path, STEP_IMAGE_CONVERSION)
                processed_steps.add(STEP_IMAGE_CONVERSION)
                log_message(f"Image conversion successful. Recorded {STEP_IMAGE_CONVERSION} to {flag_file_path}")
            else:
                log_message("Image conversion failed. Not flagging as complete.", level="ERROR")
        else:
            log_message(f"Skipping Image Conversion for {args.input_file} (already processed).")

        # ---- HTML Generation Step ----
        # Check if image conversion is done (either just now or previously) or if files physically exist (as a fallback)
        # A simple check for one of the expected output files from image conversion:
        expected_image_file_check = IMAGE_DIR / f"{current_base_name}-640w.jpg"
        if (STEP_IMAGE_CONVERSION in processed_steps or expected_image_file_check.exists()):
            if STEP_HTML_GENERATION not in processed_steps:
                log_message(f"Running HTML Generation for {args.input_file}...")

                raw_content_url_prefix = f"https://raw.githubusercontent.com/{args.github_repository}/{args.github_ref_for_raw_url}/"
                output_html_file = HTML_DIR / f"{current_base_name}.html"

                widths = [1920, 1280, 640] # Ensure widths is available
                webp_srcset_parts = []
                jpeg_srcset_parts = []

                for width_val in widths:
                    webp_src = f"{raw_content_url_prefix}processed_media/images/{current_base_name}-{width_val}w.webp"
                    jpeg_src = f"{raw_content_url_prefix}processed_media/images/{current_base_name}-{width_val}w.jpg"
                    webp_srcset_parts.append(f"{webp_src} {width_val}w")
                    jpeg_srcset_parts.append(f"{jpeg_src} {width_val}w")

                webp_srcset = ", ".join(webp_srcset_parts)
                jpeg_srcset = ", ".join(jpeg_srcset_parts)

                fallback_img_src = f"{raw_content_url_prefix}processed_media/images/{current_base_name}-640w.jpg"

                # Escape alt text for HTML attributes
                escaped_alt_text = full_description_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")

                # Read HTML template
                template_path = Path(__file__).parent / "templates" / "media_template.html"
                try:
                    with open(template_path, "r", encoding="utf-8") as f_template:
                        html_template_content = f_template.read()

                    # Populate template
                    html_content = html_template_content.replace("{{TITLE}}", current_base_name)
                    html_content = html_content.replace("{{BASE_NAME}}", current_base_name)
                    html_content = html_content.replace("{{WEBP_SRCSET}}", webp_srcset)
                    html_content = html_content.replace("{{JPEG_SRCSET}}", jpeg_srcset)
                    html_content = html_content.replace("{{FALLBACK_IMG_SRC}}", fallback_img_src)
                    html_content = html_content.replace("{{ALT_TEXT}}", escaped_alt_text)

                    with open(output_html_file, "w", encoding="utf-8") as f_html:
                        f_html.write(html_content)
                    log_message(f"Generated HTML file: {output_html_file} from template (using raw GitHub URLs)")
                    record_step_in_flag_file(flag_file_path, STEP_HTML_GENERATION)
                except FileNotFoundError:
                    log_message(f"Error: HTML template file not found at {template_path}", level="ERROR")
                except IOError as e:
                    log_message(f"Error reading HTML template or writing HTML file {output_html_file}: {e}", level="ERROR")
            else:
                log_message(f"Skipping HTML Generation for {args.input_file} (already processed).")
                    processed_steps.add(STEP_HTML_GENERATION)
                except IOError as e:
                    log_message(f"Error writing HTML file {output_html_file}: {e}", level="ERROR")
            else:
                log_message(f"Skipping HTML Generation for {args.input_file} (already processed).")
        else:
            log_message(f"Skipping HTML Generation for {args.input_file} because image conversion step is not flagged as complete or expected image files are missing.")

    elif is_video:
        if STEP_VIDEO_CONVERSION not in processed_steps:
            log_message(f"Running Video Conversion step for {args.input_file}...")
            heights = [1080, 720]
            conversion_ok = True
            for height in heights:
                try:
                    # MP4 (H.264)
                    output_mp4_path = VIDEO_DIR / f"{current_base_name}-{height}p.mp4"
                    cmd_ffmpeg_mp4 = [
                        "ffmpeg", "-i", args.input_file,
                        "-vf", f"scale=-2:min(ih\\,{height})", # Note: Escaping comma for shell, not strictly needed for list arg in Python unless it was one string
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        str(output_mp4_path), "-y"
                    ]
                    subprocess.run(cmd_ffmpeg_mp4, check=True, capture_output=True)
                    cmd_exif_mp4 = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_mp4_path)
                    ]
                    subprocess.run(cmd_exif_mp4, check=False, capture_output=True)
                    if (output_mp4_path.parent / f"{output_mp4_path.name}_original").exists():
                        (output_mp4_path.parent / f"{output_mp4_path.name}_original").unlink()

                    # WebM (VP9)
                    output_webm_path = VIDEO_DIR / f"{current_base_name}-{height}p.webm"
                    cmd_ffmpeg_webm = [
                        "ffmpeg", "-i", args.input_file,
                        "-vf", f"scale=-2:min(ih\\,{height})",
                        "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
                        "-c:a", "libopus", "-b:a", "128k",
                        str(output_webm_path), "-y"
                    ]
                    subprocess.run(cmd_ffmpeg_webm, check=True, capture_output=True)
                    cmd_exif_webm = [
                        "exiftool", "-tagsFromFile", args.input_file, "-all:all", "-overwrite_original", str(output_webm_path)
                    ]
                    subprocess.run(cmd_exif_webm, check=False, capture_output=True)
                    if (output_webm_path.parent / f"{output_webm_path.name}_original").exists():
                        (output_webm_path.parent / f"{output_webm_path.name}_original").unlink()

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
                record_step_in_flag_file(flag_file_path, STEP_VIDEO_CONVERSION)
                processed_steps.add(STEP_VIDEO_CONVERSION)
                log_message(f"Video conversion successful. Recorded {STEP_VIDEO_CONVERSION} to {flag_file_path}")
            else:
                log_message("Video conversion failed. Not flagging as complete.", level="ERROR")
        else:
            log_message(f"Skipping Video Conversion for {args.input_file} (already processed).")
    else:
        log_message(f"File {args.input_file} is not a recognized image or video type for media processing. Extension: {file_extension}")


    log_message(f"Finished processing for file: {args.input_file}")

def read_flag_file(flag_path: Path) -> tuple[set[str], str | None]:
    """Reads the flag file and returns a set of processed steps and the base_name if found."""
    processed_steps = set()
    base_name = None
    if flag_path.exists():
        log_message(f"Reading flag file: {flag_path}")
        with open(flag_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(BASE_NAME_FLAG_PREFIX):
                    base_name = line.replace(BASE_NAME_FLAG_PREFIX, "", 1)
                elif line: # Non-empty line
                    processed_steps.add(line)
    return processed_steps, base_name

def record_step_in_flag_file(flag_path: Path, step_keyword: str):
    """Appends a step keyword to the flag file if not already present."""
    if flag_path.exists():
        with open(flag_path, "r+", encoding="utf-8") as f:
            existing_steps = {line.strip() for line in f}
            if step_keyword not in existing_steps:
                f.seek(0, os.SEEK_END) # Go to the end of file
                if f.tell() > 0: # If file is not empty, add a newline
                     # Check if the last char is a newline
                    f.seek(f.tell() -1, os.SEEK_SET)
                    if f.read(1) != '\n':
                        f.write('\n')
                f.write(f"{step_keyword}\n")
                log_message(f"Recorded step '{step_keyword}' to {flag_path}")
            else:
                log_message(f"Step '{step_keyword}' already in {flag_path}")
    else: # File does not exist, create it and write the step
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write(f"{step_keyword}\n")
        log_message(f"Created flag file {flag_path} and recorded step '{step_keyword}'")

def record_base_name_in_flag_file(flag_path: Path, base_name: str):
    """Adds or updates the base_name line in the flag file."""
    base_name_line = f"{BASE_NAME_FLAG_PREFIX}{base_name}"
    lines = []
    found_base_name = False
    if flag_path.exists():
        with open(flag_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        with open(flag_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.strip().startswith(BASE_NAME_FLAG_PREFIX):
                    f.write(f"{base_name_line}\n")
                    found_base_name = True
                else:
                    f.write(line)
            if not found_base_name:
                # Ensure there's a newline if adding to an existing file with other content
                if lines and not lines[-1].endswith('\n'):
                    f.write('\n')
                f.write(f"{base_name_line}\n")
        log_message(f"Recorded base_name '{base_name}' to {flag_path}")
    else: # File does not exist, create it
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write(f"{base_name_line}\n")
        log_message(f"Created flag file {flag_path} and recorded base_name '{base_name}'")


if __name__ == "__main__":
    main()
