import google.generativeai as genai
import argparse
import os
import re
import sys

def sanitize_filename(text):
    """Sanitizes text to be filename-friendly."""
    text = text.lower()
    text = re.sub(r'\s+', '-', text)  # Replace spaces with hyphens
    text = re.sub(r'[^a-z0-9\-]', '', text)  # Remove non-alphanumeric characters except hyphens
    text = text.strip('-')
    return text[:100] # Limit length to avoid overly long filenames

def get_descriptions(api_key, file_path, output_dir):
    """
    Gets a concise filename and a full description of a media file using the Gemini API.
    Saves the full description to a .md file.
    Returns the sanitized concise filename.
    """
    genai.configure(api_key=api_key)

    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}", file=sys.stderr)
        return "error-file-not-found"

    try:
        print(f"Uploading file: {file_path} to Gemini API...", file=sys.stderr)
        sample_file = genai.upload_file(path=file_path)
        print(f"File uploaded successfully: {sample_file.name}", file=sys.stderr)
        print(f"File URI: {sample_file.uri}", file=sys.stderr)

        model = genai.GenerativeModel(model_name="gemini-1.5-flash")

        # Prompt for concise filename
        prompt_filename = "Provide a concise, descriptive filename (5-10 words) for this media, suitable for use as a base for a web filename. Focus on the main subject and action. Output only the filename."
        print("Generating concise filename with Gemini 1.5 Flash...", file=sys.stderr)
        response_filename = model.generate_content([prompt_filename, sample_file])

        # Prompt for full description
        prompt_full_desc = "Provide a full, detailed description for this media, suitable for use as an image caption or alt text. Describe the scene, subjects, colors, and any notable features."
        print("Generating full description with Gemini 1.5 Flash...", file=sys.stderr)
        response_full_desc = model.generate_content([prompt_full_desc, sample_file])

        print(f"Deleting uploaded file: {sample_file.name}", file=sys.stderr)
        genai.delete_file(sample_file.name)
        print("Uploaded file deleted.", file=sys.stderr)

        concise_filename_text = "generic-media-file"
        if response_filename and response_filename.text:
            sanitized_filename = sanitize_filename(response_filename.text)
            if sanitized_filename:
                concise_filename_text = sanitized_filename
        else:
            print("Error: No concise filename generated.", file=sys.stderr)
            # Keep concise_filename_text as "generic-media-file"

        full_description_text = "No detailed description available."
        if response_full_desc and response_full_desc.text:
            full_description_text = response_full_desc.text.strip()
        else:
            print("Error: No full description generated.", file=sys.stderr)

        # Save the full description to a .md file
        # The filename of the .md file will be based on the concise_filename_text
        md_filename = os.path.join(output_dir, f"{concise_filename_text}.md")
        try:
            os.makedirs(os.path.dirname(md_filename), exist_ok=True) # Ensure directory exists
            with open(md_filename, "w", encoding="utf-8") as f:
                f.write(full_description_text)
            print(f"Full description saved to: {md_filename}", file=sys.stderr)
        except Exception as e:
            print(f"Error saving full description to {md_filename}: {e}", file=sys.stderr)
            # Continue anyway, returning the concise filename

        return concise_filename_text

    except Exception as e:
        print(f"Error interacting with Gemini API: {e}", file=sys.stderr)
        error_msg = sanitize_filename(str(e))
        # Save a placeholder .md file if API interaction fails catastrophically
        fallback_filename = f"error-api-failed-{error_msg}"
        md_filename = os.path.join(output_dir, f"{fallback_filename}.md")
        try:
            os.makedirs(os.path.dirname(md_filename), exist_ok=True)
            with open(md_filename, "w", encoding="utf-8") as f:
                f.write("Error interacting with Gemini API. No description available.")
            print(f"Fallback description saved to: {md_filename}", file=sys.stderr)
        except Exception as e_save:
            print(f"Error saving fallback description: {e_save}", file=sys.stderr)
        return fallback_filename


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get media description from Gemini API and save full description.")
    parser.add_argument("api_key", help="Gemini API Key")
    parser.add_argument("file_path", help="Path to the media file")
    parser.add_argument("output_dir", help="Directory to save the .md file (e.g., processed_media/descriptions)")
    args = parser.parse_args()

    # Ensure the output directory for .md files exists, relative to the script's CWD (which is repo root in Actions)
    # The workflow will create processed_media/images, processed_media/videos.
    # Let's make a similar top-level directory for descriptions.
    description_output_dir = args.output_dir # This will be passed from the workflow

    # The script now expects output_dir to be created by the workflow if it's specific
    # For now, let's assume the workflow passes a valid, existing path or a path that can be created.

    concise_filename = get_descriptions(args.api_key, args.file_path, description_output_dir)
    print(concise_filename) # This goes to stdout and is captured by the workflow
