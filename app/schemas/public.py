from pydantic import BaseModel, ConfigDict


class ApproveEstimateRequest(BaseModel):
    estimate_pdf_version: str = "1"


class ApproveEstimateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    company_id: str
    estimate_id: str
    status: str = "approved"
