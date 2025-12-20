from pathlib import Path
import os

OUTPUT_FOLDER_NAME = os.environ.get("IRDRONE_WORKING_DIR", r"C://Air-Mission")
OUTPUT_FOLDER_NAME = Path(OUTPUT_FOLDER_NAME)
assert (
    OUTPUT_FOLDER_NAME.exists()
), f"Output folder does not exist: {OUTPUT_FOLDER_NAME} Use export IRDRONE_WORKING_DIR=your_path_to_folder to set it."
