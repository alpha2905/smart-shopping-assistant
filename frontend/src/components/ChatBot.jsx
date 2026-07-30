import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000';

const QUICK_ACTIONS = [
  { text: '👋 Xin chào', intent: 'greeting' },
  { text: '💡 Gợi ý điện thoại', intent: 'recommend' },
  { text: '💰 Giá rẻ nhất', intent: 'cheapest' },
  { text: '📖 Hướng dẫn', intent: 'help' },
];

export default function ChatBot() {
  const [messages, setMessages] = useState([
    {
      role: 'bot',
      text: '👋 *Xin chào!* Tôi là trợ lý mua sắm thông minh.\n\nTôi có thể giúp bạn tìm kiếm, so sánh giá và dự báo giá sản phẩm công nghệ từ 7 cửa hàng lớn nhất Việt Nam!\n\nHãy thử hỏi tôi bất cứ điều gì về sản phẩm nhé! 🚀',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const formatText = (text) => {
    // Convert markdown-style bold to HTML
    let html = text
      .replace(/\*(.*?)\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br/>');
    return html;
  };

  const sendMessage = async (messageText) => {
    const userMessage = messageText || input;
    if (!userMessage.trim() || loading) return;

    // Add user message
    setMessages((prev) => [...prev, { role: 'user', text: userMessage }]);
    setInput('');
    setLoading(true);

    try {
      const response = await axios.post(`${API_BASE}/api/chat`, {
        message: userMessage,
      });

      const botText = response.data.text || 'Xin lỗi, tôi chưa thể xử lý yêu cầu này.';
      setMessages((prev) => [...prev, { role: 'bot', text: botText }]);
    } catch (err) {
      console.error('Chat error:', err);
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          text: '❌ *Có lỗi kết nối!*\n\nVui lòng đảm bảo backend đang chạy ở http://localhost:8000 và thử lại.',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <>
      {/* Chat toggle button */}
      <button
        className={`chat-toggle-btn ${isOpen ? 'open' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
        title="Trợ lý mua sắm"
      >
        {isOpen ? '✕' : '💬'}
      </button>

      {/* Chat window */}
      {isOpen && (
        <div className="chat-window">
          {/* Header */}
          <div className="chat-header">
            <div className="chat-header-info">
              <span className="chat-avatar">🤖</span>
              <div>
                <div className="chat-title">Trợ lý mua sắm</div>
                <div className="chat-status">🟢 Online</div>
              </div>
            </div>
            <button className="chat-close-btn" onClick={() => setIsOpen(false)}>
              ✕
            </button>
          </div>

          {/* Messages */}
          <div className="chat-messages">
            {messages.map((msg, index) => (
              <div key={index} className={`chat-message ${msg.role === 'user' ? 'user' : 'bot'}`}>
                {msg.role === 'bot' && <div className="message-avatar">🤖</div>}
                <div
                  className="message-bubble"
                  dangerouslySetInnerHTML={{ __html: formatText(msg.text) }}
                />
                {msg.role === 'user' && <div className="message-avatar user-avatar">👤</div>}
              </div>
            ))}

            {loading && (
              <div className="chat-message bot">
                <div className="message-avatar">🤖</div>
                <div className="message-bubble loading-bubble">
                  <div className="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick actions */}
          {messages.length <= 2 && (
            <div className="chat-quick-actions">
              {QUICK_ACTIONS.map((action, index) => (
                <button
                  key={index}
                  className="quick-action-btn"
                  onClick={() => sendMessage(action.text)}
                  disabled={loading}
                >
                  {action.text}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div className="chat-input-area">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Nhập tin nhắn..."
              className="chat-input"
              disabled={loading}
            />
            <button
              className="chat-send-btn"
              onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
            >
              {loading ? '...' : '➤'}
            </button>
          </div>
        </div>
      )}
    </>
  );
}