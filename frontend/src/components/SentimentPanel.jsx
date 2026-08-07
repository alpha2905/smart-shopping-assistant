import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000';

// Nhãn sentiment + emoji + màu
const SENTIMENT_META = {
  positive: { label: 'Tích cực', emoji: '😍', color: '#2ecc71' },
  neutral: { label: 'Trung tính', emoji: '😐', color: '#f39c12' },
  negative: { label: 'Tiêu cực', emoji: '😠', color: '#e74c3c' },
};

function pct(v) {
  if (v == null || isNaN(v)) return '0%';
  return `${Math.round(v * 100)}%`;
}

export default function SentimentPanel({ product }) {
  const [sentiment, setSentiment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);

  const fetchResult = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        product_url: product.product_url,
        source: product.source,
      });
      const res = await axios.get(`${API_BASE}/api/sentiment/result?${params}`, {
        timeout: 10000,
      });
      if (res.data && res.data.error) {
        setSentiment(null);
        setError(res.data.error);
        return false;
      } else {
        setSentiment(res.data);
        setError(null);
        return true;
      }
    } catch (err) {
      // Backend down hoặc chưa có kết quả — để hiện nút phân tích
      setSentiment(null);
      setError('no-result');
      return false;
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        product_url: product.product_url,
        source: product.source,
      });
      await axios.post(`${API_BASE}/api/sentiment/analyze?${params}`, null, {
        timeout: 60000, // PhoBERT có thể chạy lâu
      });
      // Lấy kết quả vừa lưu
      await fetchResult();
    } catch (err) {
      setError(err.response?.data?.error || 'Lỗi khi phân tích cảm xúc');
    } finally {
      setAnalyzing(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      if (!product.product_url || !product.source) {
        setLoading(false);
        setError('no-result');
        return;
      }
      const hasResult = await fetchResult();
      if (cancelled) return;
      // Chưa có kết quả và sản phẩm có comments → TỰ ĐỘNG phân tích PhoBERT
      // (không cần user bấm nút thủ công)
      if (!hasResult && (product.comments || []).length > 0) {
        await handleAnalyze();
      }
    };
    init();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.product_url, product.source]);

  // Đang tải
  if (loading) {
    return (
      <div className="sentiment-loading">
        <div className="inline-chart-spinner"></div>
      </div>
    );
  }

  // Chưa có kết quả → hiện trạng thái phân tích hoặc nút phân tích thủ công
  if (!sentiment) {
    return (
      <div className="sentiment-empty">
        <span className="sentiment-empty-emoji">🧠</span>
        {analyzing ? (
          <div className="sentiment-analyzing">
            <div className="inline-chart-spinner"></div>
            <span className="sentiment-empty-text">Đang phân tích cảm xúc bình luận bằng PhoBERT...</span>
          </div>
        ) : (
          <>
            <span className="sentiment-empty-text">Chưa phân tích cảm xúc bình luận (PhoBERT)</span>
            <button
              className="sentiment-analyze-btn"
              onClick={handleAnalyze}
              disabled={analyzing}
            >
              🔬 Phân tích bằng PhoBERT
            </button>
          </>
        )}
        {error && error !== 'no-result' && (
          <span className="sentiment-error">⚠️ {error}</span>
        )}
      </div>
    );
  }

  const meta = SENTIMENT_META[sentiment.sentiment] || SENTIMENT_META.neutral;
  const total = sentiment.comment_count || 0;

  return (
    <div className="sentiment-panel">
      <div className="sentiment-header">
        <span className="sentiment-badge">
          🧠 Cảm xúc bình luận · PhoBERT
        </span>
        <span className="sentiment-main" style={{ color: meta.color }}>
          {meta.emoji} {meta.label} · {pct(
            sentiment.sentiment === 'positive'
              ? sentiment.positive
              : sentiment.sentiment === 'negative'
                ? sentiment.negative
                : sentiment.neutral
          )}
        </span>
      </div>

      <div className="sentiment-bars">
        <div className="sentiment-bar-row">
          <span className="sentiment-bar-label positive">👍 Tích cực</span>
          <div className="sentiment-bar-track">
            <div
              className="sentiment-bar-fill positive"
              style={{ width: pct(sentiment.positive) }}
            ></div>
          </div>
          <span className="sentiment-bar-value">{pct(sentiment.positive)}</span>
        </div>
        <div className="sentiment-bar-row">
          <span className="sentiment-bar-label neutral">😐 Trung tính</span>
          <div className="sentiment-bar-track">
            <div
              className="sentiment-bar-fill neutral"
              style={{ width: pct(sentiment.neutral) }}
            ></div>
          </div>
          <span className="sentiment-bar-value">{pct(sentiment.neutral)}</span>
        </div>
        <div className="sentiment-bar-row">
          <span className="sentiment-bar-label negative">😠 Tiêu cực</span>
          <div className="sentiment-bar-track">
            <div
              className="sentiment-bar-fill negative"
              style={{ width: pct(sentiment.negative) }}
            ></div>
          </div>
          <span className="sentiment-bar-value">{pct(sentiment.negative)}</span>
        </div>
      </div>

      <div className="sentiment-footer">
        <span className="sentiment-footer-item">
          💬 {total} bình luận
        </span>
        <span className="sentiment-footer-item">
          ⭐ {sentiment.rqs_stars || '—'} <em>RQS {sentiment.avg_rqs ?? '—'}/5</em>
        </span>
        <button className="sentiment-refresh-btn" onClick={fetchResult} title="Làm mới">
          🔄
        </button>
      </div>
    </div>
  );
}