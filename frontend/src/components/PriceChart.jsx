import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';

const API_BASE = 'http://localhost:8000';

export default function PriceChart({ product }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchPriceHistory = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          product_url: product.product_url,
          source: product.source,
        });
        const res = await axios.get(`${API_BASE}/api/price-history?${params}`, {
          timeout: 15000,
        });
        setData(res.data);
      } catch (err) {
        // Silent fail - just don't show chart
        setError('no-data');
      } finally {
        setLoading(false);
      }
    };
    // Only fetch if product has URL and source
    if (product.product_url && product.source) {
      fetchPriceHistory();
    } else {
      setLoading(false);
      setError('no-data');
    }
  }, [product.product_url, product.source]);

  // Prepare chart data: combine history + predictions
  const chartData = [];
  if (data && data.history && data.history.length > 0) {
    data.history.forEach((h) => {
      chartData.push({
        date: new Date(h.date).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }),
        'Giá thực tế': h.price,
        'Dự báo': null,
      });
    });
    if (data.predictions && data.predictions.length > 0) {
      // Bridge: set prediction start = last history price
      const lastHistory = data.history[data.history.length - 1];
      if (lastHistory) {
        chartData[chartData.length - 1]['Dự báo'] = lastHistory.price;
      }
      data.predictions.forEach((p) => {
        chartData.push({
          date: new Date(p.date).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }),
          'Giá thực tế': null,
          'Dự báo': p.price,
        });
      });
    }
  }

  const formatPrice = (value) => {
    if (value == null) return '';
    return new Intl.NumberFormat('vi-VN').format(value) + ' đ';
  };

  // Don't render anything if no data
  if (loading) {
    return (
      <div className="inline-chart-loading">
        <div className="inline-chart-spinner"></div>
      </div>
    );
  }

  if (error || !data || !data.history || data.history.length === 0) {
    return null; // Don't show chart if no price history
  }

  return (
    <div className="inline-price-chart">
      <div className="inline-chart-info">
        <span className={`inline-chart-badge ${data.cached ? 'cached' : 'fresh'}`}>
          {data.cached ? '⚡' : '🔄'} {data.model_type === 'lstm' ? 'LSTM' : 'LR'}
        </span>
        <span className="inline-chart-count">
          {data.history.length} lịch sử → {data.predictions?.length || 0} dự báo
        </span>
      </div>
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={chartData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="date" stroke="#666" fontSize={8} />
            <YAxis
              stroke="#666"
              fontSize={8}
              tickFormatter={(v) => (v ? (v / 1000000).toFixed(0) + 'M' : '')}
              width={30}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1a1a2e',
                border: '1px solid #333',
                borderRadius: '6px',
                fontSize: '0.75rem',
              }}
              formatter={(value) => formatPrice(value)}
            />
            <ReferenceLine
              x={data.history ? new Date(data.history[data.history.length - 1].date).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }) : ''}
              stroke="#e74c3c"
              strokeDasharray="3 3"
            />
            <Line
              type="monotone"
              dataKey="Giá thực tế"
              stroke="#2ecc71"
              strokeWidth={2}
              dot={{ r: 2, fill: '#2ecc71' }}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="Dự báo"
              stroke="#e67e22"
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={{ r: 2, fill: '#e67e22' }}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}