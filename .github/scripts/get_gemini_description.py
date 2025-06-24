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

def get_description(api_key, file_path):
    """
    Gets a description of an image or video file using the Gemini API.
    """
    genai.configure(api_key=api_key)

    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}", file=sys.stderr)
        return "error-file-not-found" # This return goes to stdout, which is fine for errors handled by the shell script

    try:
        print(f"Uploading file: {file_path} to Gemini API...", file=sys.stderr)
        # Gemini API can now take direct file uploads for analysis with gemini-pro-vision
        # For large files or specific needs, direct byte upload might be better,
        # but for simplicity, we'll use the file upload feature if available or adapt.
        # The SDK's `generate_content` with a Part representing the file is the way.

        sample_file = genai.upload_file(path=file_path)
        print(f"File uploaded successfully: {sample_file.name}", file=sys.stderr)
        print(f"File URI: {sample_file.uri}", file=sys.stderr)


        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        prompt = "Provide a concise, descriptive filename (5-10 words) for this media, suitable for use as a base for a web filename. Focus on the main subject and action."

        print("Generating content with Gemini 1.5 Flash...", file=sys.stderr)
        response = model.generate_content([prompt, sample_file])

        # Clean up the uploaded file once we have the response.
        print(f"Deleting uploaded file: {sample_file.name}", file=sys.stderr)
        genai.delete_file(sample_file.name)
        print("Uploaded file deleted.", file=sys.stderr)

        if response and response.text:
            sanitized = sanitize_filename(response.text)
            if not sanitized: # Handle cases where sanitization results in an empty string
                return "generic-media-file" # This return goes to stdout
            return sanitized # This return goes to stdout
        else:
            return "error-no-description-generated" # This return goes to stdout

    except Exception as e:
        print(f"Error interacting with Gemini API: {e}", file=sys.stderr)
        # Fallback filename in case of any API error
        return f"error-api-failed-{sanitize_filename(str(e))}" # This return goes to stdout

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get media description from Gemini API.")
    parser.add_argument("api_key", help="Gemini API Key")
    parser.add_argument("file_path", help="Path to the media file")
    args = parser.parse_args()

    description = get_description(args.api_key, args.file_path)
    print(description)
