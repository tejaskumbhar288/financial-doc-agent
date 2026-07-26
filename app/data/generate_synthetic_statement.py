"""
Generates a synthetic bank statement for testing StatementExtraction.

Real statement data is too PII-sensitive to source publicly, so we
generate our own with known-answer PII — this
also gives the Guard Agent (later checkpoint) something concrete to test
redaction against, since we know exactly what PII we planted.
"""

from datetime import date, timedelta
from decimal import Decimal
from random import choice, randint

from faker import Faker

from app.schemas.statement import StatementExtraction, StatementTransaction, TransactionType

fake = Faker()


def generate_synthetic_statement() -> StatementExtraction:
    period_start = date(2024, 1, 1)
    period_end = date(2024, 1, 31)

    transactions = []
    running = Decimal("2500.00")
    for _ in range(5):
        amount = Decimal(str(round(randint(5, 300) + 0.99, 2)))
        ttype = choice([TransactionType.DEBIT, TransactionType.CREDIT])
        running += amount if ttype == TransactionType.CREDIT else -amount
        transactions.append(
            StatementTransaction(
                transaction_date=period_start + timedelta(days=randint(0, 30)),
                description=fake.company(),
                amount=amount,
                transaction_type=ttype,
                running_balance=running,
            )
        )

    raw_account_number = fake.bban()
    redacted_account_number = f"****{raw_account_number[-4:]}"

    return StatementExtraction(
        source_filename="synthetic_statement_001.pdf",
        confidence_score=0.98,
        account_holder_name=fake.name(),
        bank_name=fake.company() + " Bank",
        account_number_redacted=redacted_account_number,
        routing_number_redacted="****" + str(randint(1000, 9999)),
        statement_period_start=period_start,
        statement_period_end=period_end,
        opening_balance=Decimal("2500.00"),
        closing_balance=running,
        transactions=transactions,
    )


if __name__ == "__main__":
    stmt = generate_synthetic_statement()
    print(stmt.model_dump_json(indent=2))
