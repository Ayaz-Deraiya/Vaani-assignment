# The Relay | V1

This milestone answers questions from the three versioned papers. It retrieves passages, validates exact quotations and citations, and refuses when evidence is insufficient. It includes the paper index and six pipeline tests.

From the project directory, install the requirements and run:

    python -m pip install -r requirements.txt
    python -m unittest -q test_pipeline

Set GROQ_API_KEY in your environment to try a live question:

    python ask.py "What is Moshi's theoretical latency?"

The next milestone adds measurement, quota simulation and load testing.
