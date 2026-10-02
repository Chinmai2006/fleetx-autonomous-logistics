from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from protocols.messages import Location, TaskCreate


class RoutePlanRequest(BaseModel):
    origin: str
    destination: str
    origin_location: Optional[Location] = None
    destination_location: Optional[Location] = None
    waypoints: List[Location] = Field(default_factory=list)
    estimated_distance_km: Optional[float] = Field(default=None, ge=0)
    coordinate_unit: str = "m"
    average_speed_kph: float = Field(default=20.0, gt=0, le=300)
    payload_weight_kg: float = Field(default=0.0, ge=0)
    priority: int = Field(default=3, ge=1, le=5)


class RoutePlan(BaseModel):
    provider: str
    origin: str
    destination: str
    points: List[Location] = Field(default_factory=list)
    distance_km: float
    estimated_travel_time_minutes: float
    route_cost: float
    distance_source: str
    explanation: str


class RoutingProvider(ABC):
    @abstractmethod
    def plan(self, request: RoutePlanRequest) -> RoutePlan:
        raise NotImplementedError


class LocalEuclideanProvider(RoutingProvider):
    """Plans over explicitly supplied local coordinates; does not imply road routing."""

    def plan(self, request: RoutePlanRequest) -> RoutePlan:
        points = []
        if request.origin_location is not None:
            points.append(request.origin_location)
        points.extend(request.waypoints)
        if request.destination_location is not None:
            points.append(request.destination_location)

        if request.estimated_distance_km is not None:
            distance = request.estimated_distance_km
            source = "caller_supplied_distance"
        elif len(points) >= 2:
            unit_scale = 0.001 if request.coordinate_unit == "m" else 1.0
            if request.coordinate_unit not in ("m", "km"):
                raise HTTPException(status_code=422, detail="coordinate_unit must be 'm' or 'km'")
            distance = sum(
                math.dist((left.x, left.y), (right.x, right.y)) * unit_scale
                for left, right in zip(points, points[1:])
            )
            source = f"explicit_local_coordinates_{request.coordinate_unit}"
        else:
            raise HTTPException(
                status_code=422,
                detail="Provide an estimated distance or explicit origin and destination coordinates",
            )

        travel_minutes = distance / request.average_speed_kph * 60.0
        priority_factor = 1.0 + (5 - request.priority) * 0.03
        payload_factor = 1.0 + request.payload_weight_kg * 0.002
        cost = distance * priority_factor * payload_factor
        return RoutePlan(
            provider="local_euclidean",
            origin=request.origin,
            destination=request.destination,
            points=points,
            distance_km=distance,
            estimated_travel_time_minutes=travel_minutes,
            route_cost=cost,
            distance_source=source,
            explanation=(
                "Distance uses explicitly supplied local coordinates or caller-reported distance; "
                "no traffic or road-network data is integrated."
            ),
        )


class RoutePlanner:
    def __init__(self, provider: Optional[RoutingProvider] = None):
        self.provider = provider or LocalEuclideanProvider()

    def plan(self, request: RoutePlanRequest) -> RoutePlan:
        return self.provider.plan(request)

    def plan_task(self, task: TaskCreate) -> RoutePlan:
        return self.plan(
            RoutePlanRequest(
                origin=task.origin,
                destination=task.destination,
                origin_location=task.origin_location,
                destination_location=task.destination_location,
                waypoints=task.waypoints,
                estimated_distance_km=task.estimated_distance_km,
                payload_weight_kg=task.payload_weight,
                priority=task.priority,
            )
        )


route_planner = RoutePlanner()