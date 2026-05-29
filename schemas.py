from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


DocType = Literal["permis", "cin", "carte_grise", "assurance"]
Status = Literal["ok", "review", "failed"]


class PermisData(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    numero: str | None = None
    date_naissance: str | None = None
    date_delivrance: str | None = None
    date_expiration: str | None = None
    categories: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_text: str = ""


class CINData(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    pere: str | None = None
    numero_cin: str | None = None
    date_naissance: str | None = None
    date_delivrance: str | None = None
    gouvernorat: str | None = None
    language_detected: Literal["ar", "fr", "mixed"] = "fr"
    raw_text: str = ""


class CarteGriseData(BaseModel):
    immatriculation: str | None = None
    vin: str | None = None
    marque: str | None = None
    annee: str | None = None
    raw_text: str = ""


class AssuranceData(BaseModel):
    numero_police: str | None = None
    date_debut: str | None = None
    date_fin: str | None = None
    compagnie: str | None = None
    raw_text: str = ""


ParsedData = Union[PermisData, CINData, CarteGriseData, AssuranceData]


class OCRExtractPayload(BaseModel):
    doc_type: DocType
    confidence: float
    status: Status
    data: dict[str, Any]
    processing_time_ms: int


class OCRExtractResponse(BaseModel):
    success: Literal[True] = True
    data: OCRExtractPayload


class OCRErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class OCRErrorResponse(BaseModel):
    success: Literal[False] = False
    error: OCRErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok", "loading"]
    model: str = "paddleocr"
    langs: list[str] = Field(default_factory=lambda: ["ar", "fr"])
