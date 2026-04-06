# Urban Growth Strategy Selection Policy Scenario

## Scenario Overview

This scenario models how a metropolitan city evaluates competing strategies for future growth in housing, employment, transportation access, and neighborhood development. The scenario is inspired by large-scale city planning efforts in which policymakers must compare several urban growth alternatives.

The problem is especially suitable for MCDM because growth strategies produce competing outcomes. One strategy may maximize housing capacity, while another may improve transit accessibility, reduce displacement, or better align with sustainability goals. This scenario was inspired by One Seattle Plan Update.

## Why this scenario

This scenarios is strong for the thesis for several reasons:

- It is based on a real policy scenario
- It allows the use of urban data
- It supports scenario comparisons under changing policy priorities

## Policy Question

Which growth strategy should the city adopt in order to accommodate future housing and economic development while balancing affordability, equity, sustainability, transit access, and infrastructure constraints?

## Decision Makers

The primary users and stakeholders in the scenario may include:

- City council members
- Planning and zoning officials
- Housing department officials
- Transportation and transit planners
- Sustainability office representatives
- Economic development staff
- Community advisory groups
- Neighborhood planning committees

## Alternatives

### Alternative A — No Action

The no action alternative is required under the State environment Policy Act (SEPA). The alternative maintains the status quo of focusing on housing and jobs exiting within urban centers and villages with no change to land use patterns.

### Alternative A — Focused Centers

Growth is concentrated in neighborhood centers near existing shops, services, and activity hubs.

### Alternative B — Broad Neighborhood Housing

Middle housing such as duplexes, triplexes, and fourplexes is expanded across most residential neighborhoods.

### Alternative C — Transit Corridor Growth

A larger share of housing growth is directed toward major transit corridors and amenity-rich areas.

### Alternative D — Combined Distributed Growth

A hybrid strategy that uses neighborhood centers, transit corridors, and broader housing flexibility to expand citywide capacity.

### Example data Inputs

The system could store a structured row of values for each alternative.

| Alternative | New Housing Capacity | Transit Access % | Affordability Score | Displacement Risk | Infrastructure Cost (USD) | Climate Benefit Score | Public Support % |
|---|---:|---:|---:|---:|---:|---:|---:|
| No Action | 32000 | 46 | 4.8 | 0.22 | 900000000 | 4.9 | 58 |
| Focused Centers | 72000 | 58 | 6.4 | 0.41 | 1800000000 | 7.0 | 61 |
| Broad Neighborhood Housing | 88000 | 49 | 7.5 | 0.63 | 2100000000 | 6.4 | 46 |
| Transit Corridor Growth | 96000 | 71 | 7.2 | 0.58 | 2400000000 | 8.6 | 52 |
| Combined Distributed Growth | 112000 | 67 | 8.1 | 0.55 | 2900000000 | 8.2 | 49 |

## Example JSON Input

```json
{
    "scenario_name": "Urban Growth Strategy Selection",
    "policy_goal": "Select the best long-term city growth strategy",
    "decision_makers": [
        "City Council",
        "Planning Department",
        "Housing Office",
        "Transit Planning Office",
        "Sustainability Office",
        "Community Advisory Board"
    ],
    "alternatives": [
        {
            "id": "A",
            "name": "No Action",
            "description": "Maintain the status quo with no major land-use pattern changes."
        },
        {
            "id": "B",
            "name": "Focused Centers",
            "description": "Concentrate growth in neighborhood centers near shops and services."
        },
        {
            "id": "C",
            "name": "Broad Neighborhood Housing",
            "description": "Expand middle housing across most residential neighborhoods."
        },
        {
            "id": "D",
            "name": "Transit Corridor Growth",
            "description": "Direct a larger share of growth to transit and amenity corridors."
        },
        {
            "id": "E",
            "name": "Combined Distributed Growth",
            "description": "Use a hybrid strategy combining centers, corridors, and broader housing flexibility."
        }
    ],
    "criteria": [
        { "name": "new_housing_capacity", "type": "benefit", "unit": "units" },
        { "name": "transit_access_percent", "type": "benefit", "unit": "percent" },
        { "name": "affordability_score", "type": "benefit", "unit": "0_to_10" },
        { "name": "displacement_risk_index", "type": "cost", "unit": "0_to_1" },
        { "name": "infrastructure_cost_usd", "type": "cost", "unit": "usd" },
        { "name": "climate_benefit_score", "type": "benefit", "unit": "0_to_10" },
        { "name": "public_support_percent", "type": "benefit", "unit": "percent" }
    ],
    "input_data": [
        {
            "alternative_id": "A",
            "new_housing_capacity": 32000,
            "transit_access_percent": 46,
            "affordability_score": 4.8,
            "displacement_risk_index": 0.22,
            "infrastructure_cost_usd": 900000000,
            "climate_benefit_score": 4.9,
            "public_support_percent": 58
        },
        {
            "alternative_id": "B",
            "new_housing_capacity": 72000,
            "transit_access_percent": 58,
            "affordability_score": 6.4,
            "displacement_risk_index": 0.41,
            "infrastructure_cost_usd": 1800000000,
            "climate_benefit_score": 7.0,
            "public_support_percent": 61
        },
        {
            "alternative_id": "C",
            "new_housing_capacity": 88000,
            "transit_access_percent": 49,
            "affordability_score": 7.5,
            "displacement_risk_index": 0.63,
            "infrastructure_cost_usd": 2100000000,
            "climate_benefit_score": 6.4,
            "public_support_percent": 46
        },
        {
            "alternative_id": "D",
            "new_housing_capacity": 96000,
            "transit_access_percent": 71,
            "affordability_score": 7.2,
            "displacement_risk_index": 0.58,
            "infrastructure_cost_usd": 2400000000,
            "climate_benefit_score": 8.6,
            "public_support_percent": 52
        },
        {
            "alternative_id": "E",
            "new_housing_capacity": 112000,
            "transit_access_percent": 67,
            "affordability_score": 8.1,
            "displacement_risk_index": 0.55,
            "infrastructure_cost_usd": 2900000000,
            "climate_benefit_score": 8.2,
            "public_support_percent": 49
        }
    ]
}
```

## Data Sources

This scenario can combine real planning data with modeled scenario values.

### Real or Open Data Sources

- City comprehensive planning documents
- Zoning and parcel datasets
- Census and American Community Survey data
- Housing production and permit data
- Transit stop, route, and service-frequency data
- Capital facilities and infrastructure plans
- Environmental justice or displacement-vulnerability maps
- Neighborhood amenity and service access datasets

### Synthetic or Modeled Data Sources

- Public support scores derived from surveys
- Modeled affordability improvement estimates
- Projected displacement-risk adjustments
- Scenario-based infrastructure cost estimates
- Housing buildout projections for each alternative
- Climate benefit scoring models

## Data Storage

For this scenario i could store data in a relational database and process into the required from for the input.