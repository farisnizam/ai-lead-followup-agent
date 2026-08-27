"""Insert a handful of sample leads for manually exercising the API and,
later, the dashboard/detail UI. Safe to re-run: clears existing rows first.

Usage: python -m scripts.seed
"""

from app.db import Base, SessionLocal, engine
from app.models import Lead, LeadIntent, LeadStatus, Message, MessageDirection

SAMPLE_LEADS = [
    {
        "name": "Ariana Cole",
        "email": "ariana.cole@example.com",
        "source": "landing_page",
        "status": LeadStatus.NEW,
        "current_intent": None,
        "message": "Hi, I saw your product on the landing page and I'm curious to learn more.",
    },
    {
        "name": "Marcus Webb",
        "email": "marcus.webb@example.com",
        "source": "landing_page",
        "status": LeadStatus.CONTACTED,
        "current_intent": LeadIntent.PRICING,
        "message": "What are your pricing tiers for a team of 20?",
    },
    {
        "name": "Priya Nair",
        "email": "priya.nair@example.com",
        "source": "referral",
        "status": LeadStatus.ENGAGED,
        "current_intent": LeadIntent.INTERESTED,
        "message": "This looks like exactly what we need. Can we set up a call this week?",
    },
    {
        "name": "Diego Fernandez",
        "email": "diego.fernandez@example.com",
        "source": "landing_page",
        "status": LeadStatus.ESCALATED,
        "current_intent": LeadIntent.OBJECTION,
        "message": "I tried a competitor's tool before and it broke our workflow. Why would this be different?",
    },
    {
        "name": "Helen Ok",
        "email": "helen.ok@example.com",
        "source": "landing_page",
        "status": LeadStatus.UNSUBSCRIBED,
        "current_intent": LeadIntent.UNSUBSCRIBE,
        "message": "Please stop emailing me, not interested.",
    },
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Query(Model).delete() is a bulk SQL DELETE - it does not go through
        # the ORM identity map, so the cascade="all, delete-orphan" on Lead's
        # relationships (messages, agent_decisions, actions, ...) never
        # fires and this fails once a lead has any of those child rows.
        # db.delete(instance) does honor those cascades.
        for lead in db.query(Lead).all():
            db.delete(lead)
        db.commit()

        for entry in SAMPLE_LEADS:
            lead = Lead(
                name=entry["name"],
                email=entry["email"],
                source=entry["source"],
                status=entry["status"],
                current_intent=entry["current_intent"],
            )
            lead.messages.append(Message(direction=MessageDirection.IN, body=entry["message"]))
            db.add(lead)
        db.commit()
        print(f"Seeded {len(SAMPLE_LEADS)} leads.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
