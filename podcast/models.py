"""Shared data shapes."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Article(BaseModel):
    domain: str
    title: str
    content: str
    link: str


class Selection(BaseModel):
    """One curated pick, referenced by exact title."""
    domain: str = Field(description="tech, business, or science")
    title: str = Field(description="Exact article title from the input")
    reason: str = Field(description="Why this is newsworthy, one line")


class Curation(BaseModel):
    picks: list[Selection] = Field(description="Chosen articles, most important first")


class Turn(BaseModel):
    speaker: str = Field(description="Exactly 'Anchor' or 'Weather'")
    text: str = Field(description="Spoken text, news-bulletin register, no stage directions")


class Script(BaseModel):
    turns: list[Turn]


class FactCheck(BaseModel):
    turns: list[Turn] = Field(description="Corrected bulletin, same order and speaker tags")
    removed: list[str] = Field(description="Short notes on each claim cut or corrected")


class MarketQuote(BaseModel):
    label: str
    price: float
    change_pct: float


class Weather(BaseModel):
    city: str
    now_c: float
    high_c: float
    low_c: float
    conditions: str
    wind_kmh: float
