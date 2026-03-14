# Expecto: Extract Formal Specification from Natural Language Instruction for Trustworthy Oracle

This repository aims to improve code generation capabilities by extracting formal specifications from natural language instructions. Expecto (Extract Formal Specification from Natural Language Instruction for Testing Oracle) is a framework that helps language models better understand requirements and generate more accurate code by formalizing natural language specifications into testable assertions.

## Setup

1. Create a virtual environment (Strongly recommended)
```bash
conda create -n expecto python=3.12
conda activate expecto
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Create a `.env` file and set the `OPENAI_API_KEY` environment variable
```bash
touch .env
echo "OPENAI_API_KEY=<your-openai-api-key>" >> .env
```

4. Run the task
```bash
inspect run src/apps.py
```

## FAQ
