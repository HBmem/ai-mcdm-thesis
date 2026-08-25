from decimal import Decimal
from types import SimpleNamespace

from poli_insight.application.ports.validator import (
    PreparedComparisonMatrix,
    ValidatorMetadata,
    WeightingExecutionResult,
)
from poli_insight.application.validation.service import SubmissionValidationService
from poli_insight.domain.enum import ValidationStatus
from poli_insight.domain.validation import ValidationPreparedMatrix


class _Preparer:
    version = "test-preparer-v1"

    def prepare(self, request):
        return PreparedComparisonMatrix(
            ValidationPreparedMatrix.create(
                validation_id=request.validation_id,
                response_format="pairwise",
                value_shape="crisp",
                criterion_ids=("criterion-a", "criterion-b", "criterion-c"),
                matrix_json={
                    "values": [
                        ["1", "2", "4"],
                        ["0.5", "1", "2"],
                        ["0.25", "0.5", "1"],
                    ]
                },
                preparer_version=self.version,
            ),
            (),
        )


class _Runner:
    metadata = ValidatorMetadata(
        validator_implementation_id="algorithm-1",
        validator_version="algorithm-v1",
        adapter_version="adapter-v1",
        parameter_schema_version=1,
    )

    def __init__(self, ratio):
        self.ratio = ratio

    def execute(self, prepared, parameters):
        return WeightingExecutionResult(
            criterion_ids=prepared.criterion_ids,
            crisp_weights=(
                Decimal("0.5"),
                Decimal("0.3"),
                Decimal("0.2"),
            ),
            consistency_ratio=self.ratio,
        )


def _request(threshold=Decimal("0.1")):
    return SimpleNamespace(
        validation_id="validation-1",
        configuration=SimpleNamespace(consistency_threshold=threshold),
        algorithm_config=SimpleNamespace(
            algorithm_implementation_id="algorithm-1"
        ),
        parameter_json={},
        ensure_compatible=lambda metadata: None,
    )


def test_consistency_threshold_creates_warning_without_invalidating():
    service = SubmissionValidationService(
        _Preparer(),
        _Runner(Decimal("0.2")),
        id_factory=lambda: "message-1",
    )

    result = service.validate(_request())

    assert result.status == ValidationStatus.VALID_WITH_WARNING
    assert result.messages[0].code == "consistency.threshold_exceeded"
    assert result.consistency_ratio == Decimal("0.2")


def test_algorithm_without_consistency_capability_remains_valid():
    service = SubmissionValidationService(
        _Preparer(),
        _Runner(None),
    )

    result = service.validate(_request())

    assert result.status == ValidationStatus.VALID
    assert result.consistency_ratio is None

