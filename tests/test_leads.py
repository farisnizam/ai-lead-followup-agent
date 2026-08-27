def test_create_lead_ingests_initial_message(client):
    resp = client.post(
        "/leads",
        json={
            "name": "Test Lead",
            "email": "test.lead@example.com",
            "source": "landing_page",
            "message": "I'd like to know more about your product.",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Test Lead"
    assert body["status"] == "new"
    assert body["current_intent"] is None
    assert len(body["messages"]) == 1
    assert body["messages"][0]["direction"] == "in"
    assert body["messages"][0]["body"] == "I'd like to know more about your product."


def test_create_lead_rejects_invalid_email(client):
    resp = client.post(
        "/leads",
        json={"name": "Bad Email", "email": "not-an-email", "message": "hi"},
    )
    assert resp.status_code == 422


def test_list_leads_returns_created_leads(client):
    client.post("/leads", json={"name": "A", "email": "a@example.com", "message": "hi"})
    client.post("/leads", json={"name": "B", "email": "b@example.com", "message": "hi"})

    resp = client.get("/leads")
    assert resp.status_code == 200
    names = {lead["name"] for lead in resp.json()}
    assert {"A", "B"} <= names


def test_get_lead_returns_detail_with_messages(client):
    created = client.post(
        "/leads", json={"name": "Detail Lead", "email": "detail@example.com", "message": "hello"}
    ).json()

    resp = client.get(f"/leads/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
    assert len(resp.json()["messages"]) == 1


def test_get_lead_404_for_unknown_id(client):
    resp = client.get("/leads/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_update_lead_status(client):
    created = client.post(
        "/leads", json={"name": "Status Lead", "email": "status@example.com", "message": "hello"}
    ).json()

    resp = client.patch(f"/leads/{created['id']}", json={"status": "escalated"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "escalated"


def test_update_lead_404_for_unknown_id(client):
    resp = client.patch(
        "/leads/00000000-0000-0000-0000-000000000000", json={"status": "escalated"}
    )
    assert resp.status_code == 404


def test_update_lead_rejects_invalid_status(client):
    created = client.post(
        "/leads", json={"name": "Bad Status", "email": "badstatus@example.com", "message": "hi"}
    ).json()

    resp = client.patch(f"/leads/{created['id']}", json={"status": "not_a_real_status"})
    assert resp.status_code == 422


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
