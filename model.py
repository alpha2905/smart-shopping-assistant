# ai/sentiment/model.py
import logging
from transformers import pipeline, AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_NAME = "vinai/phobert-base-v2"

def get_sentiment_pipeline():
    """
    Initializes and returns the PhoBERT sentiment analysis pipeline.
    This function will download the model on the first run.
    """
    try:
        logger.info(f"Loading PhoBERT sentiment analysis model: {MODEL_NAME}...")
        # Load the tokenizer and model
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        
        # Create the pipeline
        sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer
        )
        logger.info("PhoBERT model loaded successfully.")
        return sentiment_pipeline
    except Exception as e:
        logger.error(f"Failed to load PhoBERT model: {e}", exc_info=True)
        raise