FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace/customs-clear/backend

RUN addgroup --system --gid 10001 customs \
    && adduser --system --uid 10001 --ingroup customs --home /nonexistent customs

COPY customs-clear/backend/requirements.txt /workspace/customs-clear/backend/requirements.txt
RUN python -m pip install --no-cache-dir -r /workspace/customs-clear/backend/requirements.txt

# Deliberately copy only runtime code and public seed data. Local .env files,
# SQLite files, logs, uploads and credentials never enter the image context.
COPY --chown=10001:10001 customs-clear/backend/app /workspace/customs-clear/backend/app
COPY --chown=10001:10001 customs-clear/backend/data /workspace/customs-clear/backend/data
COPY --chown=10001:10001 customs-clear/backend/alembic/versions /workspace/customs-clear/backend/alembic/versions
COPY --chown=10001:10001 customs-clear/backend/scripts/run_ntm_full_coverage_audit.py /workspace/customs-clear/backend/scripts/run_ntm_full_coverage_audit.py
COPY --chown=10001:10001 customs-clear/backend/scripts/run_e2e_scenarios.py /workspace/customs-clear/backend/scripts/run_e2e_scenarios.py
COPY --chown=10001:10001 customs-clear/backend/scripts/tnved_pdf_parser.py /workspace/customs-clear/backend/scripts/tnved_pdf_parser.py
COPY --chown=10001:10001 customs-clear/staging/prepare_database.py /workspace/customs-clear/staging/prepare_database.py
COPY --chown=10001:10001 backend/app/services/source_sync/data /workspace/backend/app/services/source_sync/data

USER 10001:10001

EXPOSE 8000

CMD ["sh", "-c", "python /workspace/customs-clear/staging/prepare_database.py --validate-only /data/customs.db && python scripts/run_ntm_full_coverage_audit.py --database /data/customs.db --output /tmp/ntm-full-coverage.json && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
