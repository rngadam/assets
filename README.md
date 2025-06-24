# Automated Media Processing Workflow

This repository uses a GitHub Actions workflow to automatically process image and video files uploaded to the `uploads/` directory. Processed files are optimized for web use, named based on their content (via Gemini API), and stored in the `processed_media/` directory.

## How it Works

1.  **Trigger**: The workflow runs automatically whenever changes are pushed to the `main` branch within the `uploads/` directory.
2.  **Environment Setup**: It sets up an Ubuntu environment with `ffmpeg` (for video), `ImageMagick` (for images), and Python with the `google-generativeai` library.
3.  **File Hashing & Skipping**:
    *   For each file in `uploads/`, an MD5 hash is calculated.
    *   The workflow checks if a "flag" file (named `<hash>`) exists in the `processed_flags/` directory.
    *   If the flag file exists, the input file is considered already processed and is skipped. This prevents reprocessing unchanged files.
4.  **Content Description (Gemini API)**:
    *   If the file is new, it's sent to the Google Gemini Pro Vision API to generate a concise, descriptive name based on its visual content.
    *   This description is sanitized (lowercase, hyphens for spaces, alphanumeric only) to be used as the base for output filenames.
    *   **Requires `GEMINI_API_KEY` secret to be set in the repository.**
5.  **Image Processing**:
    *   Supported image formats: JPG, JPEG, PNG, GIF, WebP.
    *   Images are converted and resized to:
        *   JPEG format (quality 85) at 1920px, 1280px, and 640px widths (aspect ratio maintained).
        *   WebP format (quality 80) at 1920px, 1280px, and 640px widths (aspect ratio maintained).
    *   Output: `processed_media/images/<gemini-description>-<width>w.<format>` (e.g., `a-cat-playing-with-yarn-1280w.webp`).
6.  **Video Processing**:
    *   Supported video formats: MP4, MOV, AVI, MKV, WebM, FLV.
    *   Videos are converted and resized to:
        *   MP4 format (H.264 video, AAC audio) at 1080p and 720p heights (scaled down only, aspect ratio maintained).
        *   WebM format (VP9 video, Opus audio) at 1080p and 720p heights (scaled down only, aspect ratio maintained).
    *   Output: `processed_media/videos/<gemini-description>-<height>p.<format>` (e.g., `sunset-over-mountains-720p.mp4`).
7.  **Flag File Creation**: After successful processing of a file (Gemini description + all format conversions), an empty flag file named after the input file's hash is created in `processed_flags/`.
8.  **Commit & Push**: All newly processed media files (in `processed_media/`) and flag files (in `processed_flags/`) are committed to the repository and pushed.

## Setup

### 1. Gemini API Key

You need a Google Gemini API key to enable content-based file naming.

1.  Obtain an API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2.  In your GitHub repository, go to `Settings` > `Secrets and variables` > `Actions`.
3.  Click `New repository secret`.
4.  Name the secret `GEMINI_API_KEY`.
5.  Paste your API key into the "Value" field.
6.  Click `Add secret`.

If the `GEMINI_API_KEY` is not set or is invalid, the workflow will use a generic name for the processed files (e.g., `generic-media-<hash-prefix>`).

### 2. Directory Structure

Ensure the following directories exist in your repository (the workflow will create them if they don't, but it's good practice to have them):

*   `uploads/`: Place raw media files here.
*   `processed_media/images/`: Output directory for processed images.
*   `processed_media/videos/`: Output directory for processed videos.
*   `processed_flags/`: Stores flag files for already processed media.

These output directories (`processed_media` and `processed_flags`) should typically be committed to your repository as they store the results of the workflow.

## Usage

1.  **Add Files**: Add new image or video files to the `uploads/` directory.
2.  **Commit and Push**: Commit the new files and push them to the `main` branch.
    ```bash
    git add uploads/your-new-file.jpg
    git commit -m "Add new media for processing"
    git push origin main
    ```
3.  **Workflow Execution**: The GitHub Action will automatically trigger, process the new files, and commit the results to `processed_media/` and `processed_flags/`. You might need to pull the changes to see the processed files locally.

## Forcing Reprocessing

If you need to reprocess a file that has already been processed (e.g., you updated the processing script or want to try a new Gemini description):

1.  **Identify the file**: Note the original filename in the `uploads/` directory.
2.  **Calculate its MD5 hash**: You can do this locally. For example, on Linux/macOS:
    ```bash
    md5sum uploads/your-file-to-reprocess.jpg
    # or on macOS
    md5 -r uploads/your-file-to-reprocess.jpg
    ```
    The output will be a hash string followed by the filename. You only need the hash string.
3.  **Delete the corresponding flag file**:
    Remove the flag file from the `processed_flags/` directory that matches this hash.
    ```bash
    git rm processed_flags/<hash_of_the_file_to_reprocess>
    git commit -m "Remove flag to reprocess <original_filename>"
    git push origin main
    ```
4.  **Trigger reprocessing**: The next time the workflow runs (e.g., by a new push to `uploads/`, or if you re-run the workflow manually on the commit that removed the flag), it will see the missing flag file and reprocess your target file. Alternatively, you can make a trivial change to the file itself (e.g., re-save it) and push that change to `uploads/`.

    *Note*: Simply deleting the flag and pushing might not be enough if the workflow trigger is strictly on changes to `uploads/`. You might need to also push a change *within* the `uploads/` directory or manually re-run the workflow. A safe way is to remove the flag, then make a tiny modification to the source file in `uploads/` (or re-add it if you had removed it) and push that.

## Workflow File

The workflow is defined in `.github/workflows/process_media.yml`.
The Python script for Gemini interaction is in `.github/scripts/get_gemini_description.py`.
