import uuid

from tests.fakes import FakeAgentClient


def test_landing_page_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Submit" in resp.text


def test_dashboard_lists_created_lead(client):
    client.post("/leads", json={"name": "Dashboard Lead", "email": "dash-page@example.com", "message": "hi"})

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Dashboard Lead" in resp.text


def test_lead_detail_page_shows_message_and_decision(client, fake_agent_client):
    fake_agent_client.current = FakeAgentClient(
        tool_name="log_note",
        tool_input={"intent": "interested", "rationale": "Clearly interested in pricing.", "note": "n"},
    )
    created = client.post(
        "/leads",
        json={"name": "Detail Page Lead", "email": "detail-page@example.com", "message": "What's the pricing?"},
    ).json()

    resp = client.get(f"/dashboard/{created['id']}")
    assert resp.status_code == 200
    assert "What&#39;s the pricing?" in resp.text or "What's the pricing?" in resp.text
    assert "Clearly interested in pricing." in resp.text


def test_lead_detail_page_404_for_unknown_lead(client):
    resp = client.get(f"/dashboard/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_outbox_page_renders(client):
    resp = client.get("/outbox")
    assert resp.status_code == 200
    assert "Outbox" in resp.text
