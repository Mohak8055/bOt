FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for uploads
RUN mkdir -p uploaded_documents profile_images

# Expose port 8000 (default)
EXPOSE 8080

# Set default environment variables
ENV PORT=8080
ENV HOST=0.0.0.0
ENV RELOAD=false

# Run the application
CMD ["python", "run.py"]
