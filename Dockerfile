FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn httpx pydantic
COPY agent_gateway.py .
EXPOSE 7000
CMD ["uvicorn", "agent_gateway:app", "--host", "0.0.0.0", "--port", "7000"]