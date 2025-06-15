#!/bin/bash

# Ensure we're using the virtual environment
source .venv/bin/activate

# Print environment info for debugging
echo "Using Python: $(which python)"
echo "Virtual env: $VIRTUAL_ENV"
echo "Mkdocs location: $(which mkdocs)"

# Run the deploy command with the virtual environment's Python
python -m mkdocs gh-deploy

echo "Deployment completed" 