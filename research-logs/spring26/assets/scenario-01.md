# AI Datacenter Siting and Conditional Approval Policy Scenario

## Scenario Overview

This scenario models a city government decision regarding whether and how to approve the construction of a new AI-oriented data center. The scenario is structured as a multi-criteria policy decision in which city officials must compare several possible courses of action.

The policy challenge emerges because AI data centers can provide economic development benefits such as jobs, tax revenue, and digital infrastructure investment, while also creating concerns about electrical demand, grid reliability, water use, land-use compatibility, environmental impact, and community acceptance.

## Why this scenario

This scenario is strong for the thesis for several reasons:

- It reflects current and policy relevant real-world issues.
- It includes multiple conflicting criteria rather than a single objective
- It combines data driven results and outcome with public perception
- It supports experimentation with multiple weighting modes such as economic growth, sustainability, and infrastructure resilience.

## Policy Question

Which policy option should the city adopt regarding a proposed AI data center, given competing concerns around economic development, infrastructure strain, environmental sustainability, and community impact?

## Decision Makers

The primary users and stakeholders in this scenario may include:

- City council members
- Planning and zoning officials
- Public utility representatives
- Economic development officers
- Environmental sustainability staff
- Water resource managers
- Community advisory board members

## Alternatives

### Alternative A — Reject Proposal

The city denies the data center proposal.

### Alternative B — Approve at Site A with Standard Conditions

The city approves the data center at a candidate site under standard permitting rules with no major additional sustainability or community obligations.

### Alternative C — Approve at Site B with Sustainability Conditions

The city approves the project at a different site, but requires renewable energy commitments, stricter efficiency measures, and water conservation requirements.

### Alternative D — Approve at Site C with Utility Upgrade and Community Benefit Conditions

The city approves the project with the requirement that the developer contributes to grid upgrades, workforce development, community benefit funding, and stronger local accountability.

## Example Data Inputs

The system could store a structured row of values for each alternative.

| Alternative | Permanent Jobs | Annual Tax Revenue (USD) | Peak Load MW | Water Use MGD | Community Support % | Grid Upgrade Cost (USD) | Land Use Score |
|---|---:|---:|---:|---:|---:|---:|---:|
| Reject | 0 | 0 | 0 | 0 | 52 | 0 | 10 |
| Site A Standard | 120 | 3800000 | 92 | 2.4 | 39 | 12000000 | 5 |
| Site B Sustainability | 140 | 4300000 | 85 | 1.8 | 48 | 18000000 | 8 |
| Site C Utility + Community | 135 | 4100000 | 80 | 1.5 | 56 | 24000000 | 7 |

## Example JSON Input

```json
{
    "scenario_name": "AI Datacenter Siting and Conditional Approval",
    "policy_goal": "Select the best municipal response to a proposed AI datacenter",
    "decision_makers": [
        "City Council",
        "Planning Department",
        "Public Utility Officials",
        "Economic Development Office",
        "Community Advisory Board"
    ],
    "alternatives": [
        {
            "id": "A",
            "name": "Reject Proposal"
        },
        {
            "id": "B",
            "name": "Approve Site A with Standard Conditions"
        },
        {
            "id": "C",
            "name": "Approve Site B with Sustainability Conditions"
        },
        {
            "id": "D",
            "name": "Approve Site C with Utility and Community Conditions"
        }
    ],
    "criteria": [
        { "name": "permanent_jobs", "type": "benefit", "unit": "count" },
        { "name": "annual_tax_revenue_usd", "type": "benefit", "unit": "usd" },
        { "name": "peak_grid_load_mw", "type": "cost", "unit": "mw" },
        { "name": "water_use_mgd", "type": "cost", "unit": "million_gallons_per_day" },
        { "name": "community_support_percent", "type": "benefit", "unit": "percent" },
        { "name": "grid_upgrade_cost_usd", "type": "cost", "unit": "usd" },
        { "name": "land_use_compatibility_score", "type": "benefit", "unit": "0_to_10" }
    ],
    "input_data": [
        {
            "alternative_id": "A",
            "permanent_jobs": 0,
            "annual_tax_revenue_usd": 0,
            "peak_grid_load_mw": 0,
            "water_use_mgd": 0,
            "community_support_percent": 52,
            "grid_upgrade_cost_usd": 0,
            "land_use_compatibility_score": 10
        },
        {
            "alternative_id": "B",
            "permanent_jobs": 120,
            "annual_tax_revenue_usd": 3800000,
            "peak_grid_load_mw": 92,
            "water_use_mgd": 2.4,
            "community_support_percent": 39,
            "grid_upgrade_cost_usd": 12000000,
            "land_use_compatibility_score": 5
        },
        {
            "alternative_id": "C",
            "permanent_jobs": 140,
            "annual_tax_revenue_usd": 4300000,
            "peak_grid_load_mw": 85,
            "water_use_mgd": 1.8,
            "community_support_percent": 48,
            "grid_upgrade_cost_usd": 18000000,
            "land_use_compatibility_score": 8
        },
        {
            "alternative_id": "D",
            "permanent_jobs": 135,
            "annual_tax_revenue_usd": 4100000,
            "peak_grid_load_mw": 80,
            "water_use_mgd": 1.5,
            "community_support_percent": 56,
            "grid_upgrade_cost_usd": 24000000,
            "land_use_compatibility_score": 7
        }
    ]
}
```

## Data Sources

This scenario can combine real-world open data with synthetic scenario values.

### Real or Open Data Sources

- City parcel and zoning data
- Land-use and comprehensive planning maps
- Electric utility infrastructure or capacity planning reports
- Water utility supply and demand data
- Environmental impact and emissions datasets
- Labor and wage statistics
- Census or demographic data
- Community survey results
- Prior case studies of large data center developments

### Synthetic or Modeled Data Sources

- Negotiated tax incentives
- Estimated operating horizon
- Community benefits package score
- Scenario-based utility upgrade cost projections
- Projected AI demand stability score
- Future renewable integration scenarios

## Data Storage

Since the data for this scenario is around a fixed proposal there may not be any need for robust data storage. The data could be stored in a JSON object.
