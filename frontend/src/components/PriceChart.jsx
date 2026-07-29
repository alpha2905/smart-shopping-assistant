import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';

const API_BASE = 'http://localhost:8000';

export default function PriceChart({ product, onClose }) {
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
          timeout: 30000,
        });
        setData(res.data);
      } catch (err) {
        console.error('Error fetching price history:', err);
        setError(err.response?.data?.error || 'Không thể tải dữ liệu giá');
      } finally {
        setLoading(false);
      }
    };
    fetchPriceHistory();
  }, [product.product_url, product.source]);

  // Prepare chart data: combine history + predictions
  const chartData = [];
  if (data && data.history) {
    data.history.forEach((h) => {
      chartData.push({
        date: new Date(h.date).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }),
        'Giá thực tế': h.price,
        'Giá dự báo': null,
      });
    });
    if (data.predictions) {
      // Add last history point as bridge
      const lastHistory = data.history[data.history.length - 1];
      if (lastHistory) {
        chartData[chartData.length - 1]['Giá dự báo'] = lastHistory.price;
      }
      data.predictions.forEach((p) => {
        chartData.push({
          date: new Date(p.date).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }),
          'Giá thực tế': null,
          'Giá dự báo': p.price,
        });
      });
    }
  }

  const formatPrice = (value) => {
    if (value == null) return '';
    return new Intl.NumberFormat('vi-VN').format(value) + ' đ';
  };

  return (
    <div className="price-chart-overlay" onClick={onClose}>
      <div className="price-chart-modal" onClick={(e) => e.stopPropagation()}>
        <div className="price-chart-header">
          <h3>📊 Biểu đồ giá - {product.name}</h3>
          <button className="price-chart-close" onClick={onClose}>✕</button>
        </div>

        <div className="price-chart-body">
          {loading && (
            <div className="price-chart-loading">
              <div className="price-chart-spinner"></div>
              <p>Đang tải dữ liệu và dự báo giá...</p>
            </div>
          )}

          {error && (
            <div className="price-chart-error">
              <span>⚠️</span>
              <p>{error}</p>
            </div>
          )}

          {data && !loading && !error && (
            <>
              <div className="price-chart-info">
                <span className={`price-chart-badge ${data.cached ? 'cached' : 'fresh'}`}>
                  {data.cached ? '⚡ Dự báo từ cache' : '🔄 Dự báo mới'}
                </span>
                <span className="price-chart-model">
                  Model: {data.model_type === 'lstm' ? '🧠 LSTM' : '📈 Linear Regression'}
                </span>
                <span className="price-chart-count">
                  {data.history?.length} điểm lịch sử → {data.predictions?.length} ngày dự báo
                </span>
              </div>

              {chartData.length > 0 && (
                <ResponsiveContainer width="100%" height={350}>
                  <LineChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#444" />
                    <XAxis dataKey="date" stroke="#aaa" fontSize={11} />
                    <YAxis
                      stroke="#aaa"
                      fontSize={11}
                      tickFormatter={(v) => (v ? (v / 1000000).toFixed(1) + 'M' : '')}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#1a1a2e',
                        border: '1px solid #333',
                        borderRadius: '8px',
                      }}
                      formatter={(value) => formatPrice(value)}
                    />
                    <Legend />
                    <ReferenceLine
                      x={data.history ? new Date(data.history[data.history.length - 1].date).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' }) : ''}
                      stroke="#e74c3c"
                      strokeDasharray="5 5"
                      label={{ value: 'Hiện tại', fill: '#e74c3c', fontSize: 10 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="Giá thực tế"
                      stroke="#2ecc71"
                      strokeWidth={3}
                      dot={{ r: 4, fill: '#2ecc71' }}
                      connectNulls={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="Giá dự báo"
                      stroke="#e67e22"
                      strokeWidth={3}
                      strokeDasharray="8 4"
                      dot={{ r: 4, fill: '#e67e22' }}
                      connectNulls={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}

              {/* Price table */}
              <div className="price-chart-table">
                <h4>Dự báo giá 7 ngày tới</h4>
                <table>
                  <thead>
                    <tr>
                      <th>Ngày</th>
                      <th>Giá dự báo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.predictions?.map((p, i) => (
                      <tr key={i}>
                        <td>{new Date(p.date).toLocaleDateString('vi-VN')}</td>
                        <td className="predicted-price">{formatPrice(p.price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}