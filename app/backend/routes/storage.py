from fastapi import APIRouter, HTTPException
import json
from pathlib import Path
from pydantic import BaseModel

from app.backend.models.schemas import ErrorResponse

router = APIRouter(prefix="/storage")

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # Navigate to project root
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

class SaveJsonRequest(BaseModel):
    filename: str
    data: dict


def _resolve_output_path(filename: str) -> Path:
    """Return the target path for a bare filename inside OUTPUTS_DIR, or raise 400.

    Rejects separators, "..", drive/stream colons and absolute paths, then verifies
    the resolved path is a direct child of the outputs directory.
    """
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or ":" in filename
        or ".." in filename
        or Path(filename).is_absolute()
    ):
        raise HTTPException(status_code=400, detail="Invalid filename: must be a plain file name inside the outputs directory")

    outputs_dir = OUTPUTS_DIR.resolve()
    file_path = (outputs_dir / filename).resolve()
    if file_path.parent != outputs_dir:
        raise HTTPException(status_code=400, detail="Invalid filename: must be a plain file name inside the outputs directory")
    return file_path


@router.post(
    path="/save-json",
    responses={
        200: {"description": "File saved successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def save_json_file(request: SaveJsonRequest):
    """Save JSON data to the project's /outputs directory."""
    # Validate before the try block so a 400 isn't rewrapped as a 500
    file_path = _resolve_output_path(request.filename)

    try:
        # Create outputs directory if it doesn't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Save JSON data to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(request.data, f, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "message": f"File saved successfully to {file_path}",
            "filename": request.filename
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
