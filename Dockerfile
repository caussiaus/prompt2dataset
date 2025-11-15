FROM python:3.11-slim

# Install system (OS-level) dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git curl wget firefox-esr libgtk-3-0 libx11-xcb1 \
        libasound2 libx11-6 libxcb1 libdbus-glib-1-2 xvfb \
        && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies for all agent requirements (expand this list as needed)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# (Optional for headless agents using Playwright) Install Playwright browsers
RUN pip install playwright && playwright install firefox

# Copy all app/agent code
COPY . /app
WORKDIR /app

# Expose the appropriate port (change 7000 to e.g. 7001, 59001 etc for each agent)
EXPOSE 7000

# Set the CMD for this agent/service (edit for each agent as needed)
CMD ["uvicorn", "agent_gateway:app", "--host", "0.0.0.0", "--port", "7000"]
