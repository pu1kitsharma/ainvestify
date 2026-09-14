"""Validate proposed measurements symbolically; do not invent observed results."""
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class QuantityRecord(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    dimension: Literal['duration', 'money', 'count', 'ratio', 'mass', 'length', 'energy', 'power', 'volume', 'temperature']
    unit: str = Field(min_length=1, max_length=40, description='Explicit unit: e.g. hours, INR, customers, fraction. Use the same unit for like quantities.')
    record_needed: str = Field(min_length=5, max_length=200)

class MeasurementPlan(BaseModel):
    question: str = Field(min_length=5, max_length=200)
    left: QuantityRecord
    operation: Literal['subtract', 'divide', 'compare']
    right: QuantityRecord
    population_basis: str = Field(min_length=5, max_length=200, description='The comparable cohort, workflow and observation windows; a proposed scope, not an observed result.')

    @model_validator(mode='after')
    def compatible_quantities(self):
        if self.operation in {'subtract', 'compare'} and (self.left.dimension != self.right.dimension or self.left.unit.strip().casefold() != self.right.unit.strip().casefold()):
            raise ValueError('Cannot subtract or compare unlike quantities. Time, money, counts and retention are separate measures; first establish explicit compatible units.')
        if self.operation == 'divide' and self.left.dimension == self.right.dimension and self.left.unit.strip().casefold() != self.right.unit.strip().casefold():
            raise ValueError('Convert to the same unit before dividing like dimensions; never mix currencies or hours and minutes without an explicit conversion.')
        return self

    def display(self):
        symbol={'subtract':'−','divide':'÷','compare':'versus'}[self.operation]
        return f'{self.left.name} ({self.left.unit}) {symbol} {self.right.name} ({self.right.unit})'
