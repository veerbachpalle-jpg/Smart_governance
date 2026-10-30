import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.modules.integrations.ml_service.client import MLComplaintClient, normalize_string_length
from app.modules.integrations.ml_service.schemas import (
    MLAnalysis,
    MLComplaintResponse,
    MLDeptScore,
)


def test_normalize_string_length():
    # Min length padding
    short = "pothole"
    res = normalize_string_length(short, "default", 20, 100)
    assert len(res) >= 20
    assert "pothole" in res

    # Max length truncation
    long_str = "a" * 300
    res = normalize_string_length(long_str, "default", 10, 50)
    assert len(res) == 50

    # None falls back to default
    res = normalize_string_length(None, "fallback", 5, 20)
    assert res == "fallback"


def test_department_name_to_code_mapping():
    client = MLComplaintClient(base_url="http://localhost:8000")
    assert client.map_dept_name_to_code("Roads") == "ROADS"
    assert client.map_dept_name_to_code("Water") == "WATER"
    assert client.map_dept_name_to_code("Electricity") == "ELEC"
    assert client.map_dept_name_to_code("Sanitation") == "SAN"
    assert client.map_dept_name_to_code("Drainage") == "DRAIN"
    assert client.map_dept_name_to_code("Parks") == "PARKS"
    assert client.map_dept_name_to_code("UnknownDept") is None


@pytest.mark.asyncio
async def test_ml_client_analyze_complaint_success():
    client = MLComplaintClient(base_url="http://mock-ml:8000", timeout=5.0)

    mock_resp_data = {
        "success": True,
        "message": "Complaint analyzed and stored successfully.",
        "complaint_id": 42,
        "ai_analysis": {
            "is_duplicate": False,
            "duplicate_of": None,
            "similarity_score": 0.0,
            "departments": ["Roads"],
            "dept_scores": [
                {"department": "Roads", "confidence": 0.97},
                {"department": "Water", "confidence": 0.02},
                {"department": "Electricity", "confidence": 0.01},
                {"department": "Sanitation", "confidence": 0.01},
                {"department": "Drainage", "confidence": 0.05},
                {"department": "Parks", "confidence": 0.01},
            ],
            "ai_confidence": 0.97,
            "priority": "High",
            "ai_summary": "[Roads] There is a huge pothole on MG Road near the bus stop causing accidents.",
        },
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = httpx.Response(
            status_code=200,
            json=mock_resp_data,
            request=httpx.Request("POST", "http://mock-ml:8000/complaints"),
        )
        mock_post.return_value = mock_response

        res = await client.analyze_complaint(
            citizen_name="Ramesh Sharma",
            contact="9876543210",
            location="Sector 12, MG Road",
            complaint_text="There is a huge pothole on MG Road near the bus stop causing accidents.",
            category="Road Damage",
        )

        assert res is not None
        assert res.success is True
        assert res.complaint_id == 42
        assert res.ai_analysis.priority == "High"
        assert res.ai_analysis.departments == ["Roads"]
        assert len(res.ai_analysis.dept_scores) == 6
        assert res.ai_analysis.dept_scores[0].confidence == 0.97


@pytest.mark.asyncio
async def test_ml_client_graceful_fallback_on_connect_error():
    client = MLComplaintClient(base_url="http://non-existent-host:9999", timeout=1.0)

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        res = await client.analyze_complaint(
            citizen_name="Test User",
            contact="9876543210",
            location="MG Road",
            complaint_text="This is a test complaint with sufficient length for validation.",
            category="Roads",
        )
        assert res is None


@pytest.mark.asyncio
async def test_ml_health_endpoint(client: httpx.AsyncClient, officer_token: str):
    with patch("app.modules.integrations.ml_service.client.MLComplaintClient.check_health") as mock_health:
        from app.modules.integrations.ml_service.schemas import MLHealthResponse

        mock_health.return_value = MLHealthResponse(
            connected=True,
            url="http://mock-ml:8000",
            status="healthy",
            model="facebook/bart-large-mnli",
            embedding_model="all-MiniLM-L6-v2",
        )

        resp = await client.get(
            "/api/v1/integrations/ml-service/health",
            headers={"Authorization": f"Bearer {officer_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["model"] == "facebook/bart-large-mnli"
