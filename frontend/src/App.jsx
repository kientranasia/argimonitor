import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler
} from 'chart.js';
import { Activity, Globe, Clock, BarChart2, Wheat, Sprout, Upload } from 'lucide-react';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api';
const SUBMIT_AUTH_STORAGE_KEY = 'agrimonitor_submit_basic';

function readStoredSubmitAuth() {
  try {
    const raw = sessionStorage.getItem(SUBMIT_AUTH_STORAGE_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw);
    if (o && typeof o.username === 'string' && typeof o.password === 'string') {
      return { username: o.username, password: o.password };
    }
  } catch (_) {
    /* ignore */
  }
  return null;
}

function storeSubmitAuth(auth) {
  sessionStorage.setItem(SUBMIT_AUTH_STORAGE_KEY, JSON.stringify(auth));
}

function clearStoredSubmitAuth() {
  sessionStorage.removeItem(SUBMIT_AUTH_STORAGE_KEY);
}

function SubmitPage() {
  const NEWS_SOURCE_DEFAULTS = {
    manual_submit: { folder_type: 'agriculture_news', category: 'other' },
    AgroMonitor: { folder_type: 'agriculture_news', category: 'agriculture' },
    AGROINFO: { folder_type: 'agriculture_news', category: 'agriculture' },
    VITIC: { folder_type: 'agriculture_news', category: 'agriculture' },
    VNExpress: { folder_type: 'agriculture_news', category: 'agriculture' },
    Vietstock: { folder_type: 'stock_news', category: 'other' },
    CafeF: { folder_type: 'stock_news', category: 'other' }
  };

  const [commodityOptions, setCommodityOptions] = useState([]);
  const [priceForm, setPriceForm] = useState({
    commodity_name: '',
    category: 'agriculture',
    market: 'Vietnam',
    region: 'Vietnam',
    price: '',
    currency: 'VND',
    unit: 'kg',
    price_type: 'spot',
    source: 'manual_submit',
    source_url: 'manual://submit'
  });
  const [newsForm, setNewsForm] = useState({
    title: '',
    link: '',
    description: '',
    source: 'manual_submit',
    category: 'other',
    folder_type: 'agriculture_news'
  });
  const [priceStatus, setPriceStatus] = useState('');
  const [newsStatus, setNewsStatus] = useState('');
  const [authConfig, setAuthConfig] = useState({ basic_auth_enabled: false, username: null });
  const [authConfigLoaded, setAuthConfigLoaded] = useState(false);
  const [submitAuth, setSubmitAuth] = useState(() => readStoredSubmitAuth());
  const [loginForm, setLoginForm] = useState({ username: 'submit_admin', password: '' });
  const [loginError, setLoginError] = useState('');
  const [submitTab, setSubmitTab] = useState('price');
  const [newsHistory, setNewsHistory] = useState([]);
  const [newsHistoryLoading, setNewsHistoryLoading] = useState(false);

  const gateOpen = !authConfig.basic_auth_enabled || submitAuth;

  const authOpts = useCallback(() => {
    if (submitAuth && authConfig.basic_auth_enabled) {
      return { auth: { username: submitAuth.username, password: submitAuth.password } };
    }
    return {};
  }, [submitAuth?.username, submitAuth?.password, authConfig.basic_auth_enabled]);

  useEffect(() => {
    const loadAuthConfig = async () => {
      try {
        const res = await axios.get(`${API_BASE}/submit/auth-config`);
        const data = res?.data || {};
        setAuthConfig({
          basic_auth_enabled: !!data.basic_auth_enabled,
          username: data.username || 'submit_admin'
        });
        if (data.basic_auth_enabled && data.username) {
          setLoginForm((prev) => ({ ...prev, username: data.username }));
        }
      } catch (err) {
        setPriceStatus(`Không tải được cấu hình submit: ${err.message}`);
      } finally {
        setAuthConfigLoaded(true);
      }
    };
    loadAuthConfig();
  }, []);

  const fetchPriceOptions = useCallback(async () => {
    const res = await axios.get(`${API_BASE}/submit/price-options`, authOpts());
    const options = res?.data?.data || [];
    setCommodityOptions(options);
    if (options.length > 0) {
      const first = options[0];
      setPriceForm((prev) => ({
        ...prev,
        commodity_name: first.commodity_name,
        category: first.category || prev.category,
        market: first.market || prev.market,
        region: first.region || prev.region,
        currency: first.currency || prev.currency,
        unit: first.unit || prev.unit,
        price_type: first.price_type || prev.price_type
      }));
    }
  }, [authOpts]);

  useEffect(() => {
    if (!authConfigLoaded || !gateOpen) return;
    const run = async () => {
      try {
        await fetchPriceOptions();
        setPriceStatus('');
      } catch (err) {
        if (err?.response?.status === 401) {
          clearStoredSubmitAuth();
          setSubmitAuth(null);
          setPriceStatus('Phiên đăng nhập hết hạn hoặc sai mật khẩu. Vui lòng đăng nhập lại.');
        } else {
          setPriceStatus(`Không tải được danh sách mặt hàng: ${err?.response?.data?.detail || err.message}`);
        }
      }
    };
    run();
  }, [authConfigLoaded, gateOpen, fetchPriceOptions]);

  const onSubmitLogin = async (e) => {
    e.preventDefault();
    setLoginError('');
    const auth = { username: loginForm.username.trim(), password: loginForm.password };
    try {
      await axios.get(`${API_BASE}/submit/price-options`, { auth });
      storeSubmitAuth(auth);
      setSubmitAuth(auth);
    } catch (err) {
      setLoginError(err?.response?.data?.detail || err.message || 'Đăng nhập thất bại');
    }
  };

  const onLogoutSubmit = () => {
    clearStoredSubmitAuth();
    setSubmitAuth(null);
    setCommodityOptions([]);
    setNewsHistory([]);
  };

  const fetchNewsHistory = useCallback(async () => {
    setNewsHistoryLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/submit/news/history`, authOpts());
      setNewsHistory(res?.data?.data || []);
    } catch (err) {
      if (err?.response?.status === 401) {
        clearStoredSubmitAuth();
        setSubmitAuth(null);
      }
    } finally {
      setNewsHistoryLoading(false);
    }
  }, [authOpts]);

  useEffect(() => {
    if (!authConfigLoaded || !gateOpen || submitTab !== 'news') return;
    fetchNewsHistory();
  }, [authConfigLoaded, gateOpen, submitTab, fetchNewsHistory]);

  const onCommodityChange = (name) => {
    const selected = commodityOptions.find((x) => x.commodity_name === name);
    if (!selected) {
      setPriceForm((prev) => ({ ...prev, commodity_name: name }));
      return;
    }
    setPriceForm((prev) => ({
      ...prev,
      commodity_name: selected.commodity_name,
      category: selected.category || prev.category,
      market: selected.market || prev.market,
      region: selected.region || prev.region,
      currency: selected.currency || prev.currency,
      unit: selected.unit || prev.unit,
      price_type: selected.price_type || prev.price_type
    }));
  };

  const submitPrice = async (e) => {
    e.preventDefault();
    setPriceStatus('Đang submit giá...');
    try {
      await axios.post(
        `${API_BASE}/submit/price`,
        {
          ...priceForm,
          price: Number(priceForm.price)
        },
        authOpts()
      );
      setPriceStatus('Đã submit giá thành công.');
      setPriceForm((prev) => ({ ...prev, price: '' }));
    } catch (err) {
      setPriceStatus(`Lỗi submit giá: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const submitNews = async (e) => {
    e.preventDefault();
    setNewsStatus('Đang submit tin và crawl metadata...');
    try {
      await axios.post(`${API_BASE}/submit/news`, newsForm, authOpts());
      setNewsStatus('Đã submit tin thành công và lưu archive .md.');
      setNewsForm({
        title: '',
        link: '',
        description: '',
        source: 'manual_submit',
        category: 'other',
        folder_type: 'agriculture_news'
      });
      fetchNewsHistory();
    } catch (err) {
      setNewsStatus(`Lỗi submit tin: ${err?.response?.data?.detail || err.message}`);
    }
  };

  const onNewsSourceChange = (source) => {
    const defaults = NEWS_SOURCE_DEFAULTS[source] || NEWS_SOURCE_DEFAULTS.manual_submit;
    setNewsForm((prev) => ({
      ...prev,
      source,
      folder_type: defaults.folder_type,
      category: defaults.category
    }));
  };

  const deleteNewsHistoryRow = async (id) => {
    if (!window.confirm('Xóa bản ghi submit này và dữ liệu tin liên kết (DB + file .md nếu có)?')) return;
    try {
      await axios.delete(`${API_BASE}/submit/news/history/${id}`, authOpts());
      await fetchNewsHistory();
      setNewsStatus('Đã xóa bản ghi lịch sử.');
    } catch (err) {
      setNewsStatus(`Lỗi xóa: ${err?.response?.data?.detail || err.message}`);
    }
  };

  return (
    <div className="dashboard-container">
      <header className="site-header">
        <div className="brand-block">
          <img src="/favicon.svg" alt="" className="brand-icon" width={22} height={22} />
          <span className="brand-name">TDI Agriculture Monitor</span>
          <span className="brand-beta">SUBMIT</span>
        </div>
        <div className="brand-meta">
          {authConfig.basic_auth_enabled && submitAuth && (
            <button type="button" className="timeframe-btn" onClick={onLogoutSubmit} style={{ fontSize: 9, padding: '2px 6px' }}>
              Đăng xuất submit
            </button>
          )}
          <a href="/" rel="noreferrer">Về trang chủ</a>
        </div>
      </header>
      <div className="main-grid" style={{ gridTemplateColumns: '1fr' }}>
        <div className="panel" style={{ minHeight: '70vh' }}>
          <div className="panel-header">Submit Data</div>
          <div className="panel-content" style={{ padding: 12 }}>
            {authConfig.basic_auth_enabled && !submitAuth && (
              <form onSubmit={onSubmitLogin} style={{ maxWidth: 420, border: '1px solid var(--border-color)', padding: 12, marginBottom: 16 }}>
                <h3 style={{ marginTop: 0 }}>Đăng nhập Submit (Basic Auth)</h3>
                <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 0 }}>
                  API n8n: cùng user/password, chọn Basic Auth trên node HTTP Request →{' '}
                  <code style={{ color: 'var(--accent)' }}>POST {API_BASE}/submit/price</code> hoặc{' '}
                  <code style={{ color: 'var(--accent)' }}>/submit/news</code>.
                </p>
                <input
                  required
                  autoComplete="username"
                  placeholder="Username"
                  value={loginForm.username}
                  onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })}
                />
                <input
                  required
                  type="password"
                  autoComplete="current-password"
                  placeholder="Password"
                  value={loginForm.password}
                  onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
                />
                <button type="submit" className="timeframe-btn active" style={{ marginTop: 8 }}>Đăng nhập</button>
                {loginError && <div style={{ marginTop: 8, color: 'var(--neon-red)' }}>{loginError}</div>}
              </form>
            )}
            {gateOpen && (
            <div>
              <div className="submit-tabs">
                <button type="button" className={`submit-tab ${submitTab === 'price' ? 'active' : ''}`} onClick={() => setSubmitTab('price')}>Giá (Price)</button>
                <button type="button" className={`submit-tab ${submitTab === 'news' ? 'active' : ''}`} onClick={() => setSubmitTab('news')}>Tin tức (NEWS)</button>
              </div>
              {submitTab === 'price' && (
              <form onSubmit={submitPrice} style={{ border: '1px solid var(--border-color)', padding: 12, maxWidth: 560 }}>
                <h3 style={{ marginTop: 0 }}>Submit giá mặt hàng</h3>
                <select required value={priceForm.commodity_name} onChange={(e) => onCommodityChange(e.target.value)}>
                  {commodityOptions.length === 0 && <option value="">Đang tải danh sách mặt hàng...</option>}
                  {commodityOptions.map((opt) => (
                    <option key={opt.commodity_name} value={opt.commodity_name}>
                      {opt.commodity_name}
                    </option>
                  ))}
                </select>
                <input required placeholder="Giá" type="number" step="0.01" value={priceForm.price} onChange={(e) => setPriceForm({ ...priceForm, price: e.target.value })} />
                <select value={priceForm.price_type} onChange={(e) => setPriceForm({ ...priceForm, price_type: e.target.value })}>
                  <option value="spot">Spot</option>
                  <option value="bid">Bid</option>
                  <option value="ask">Ask</option>
                  <option value="manual">Manual</option>
                </select>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '2px 0 8px 0', lineHeight: 1.4 }}>
                  Tự động lưu metadata: {priceForm.category} | {priceForm.market} | {priceForm.region} | {priceForm.currency}/{priceForm.unit}
                </div>
                <button type="submit" className="timeframe-btn active" style={{ marginTop: 8 }}>Submit giá</button>
                <div style={{ marginTop: 8, color: 'var(--text-secondary)' }}>{priceStatus}</div>
              </form>
              )}
              {submitTab === 'news' && (
              <div>
                <form onSubmit={submitNews} style={{ border: '1px solid var(--border-color)', padding: 12, marginBottom: 16 }}>
                  <h3 style={{ marginTop: 0 }}>Submit tin tức</h3>
                  <input required placeholder="Tiêu đề" value={newsForm.title} onChange={(e) => setNewsForm({ ...newsForm, title: e.target.value })} />
                  <input required placeholder="Link bài viết gốc" value={newsForm.link} onChange={(e) => setNewsForm({ ...newsForm, link: e.target.value })} />
                  <textarea placeholder="Description" rows={5} value={newsForm.description} onChange={(e) => setNewsForm({ ...newsForm, description: e.target.value })} />
                  <select value={newsForm.source} onChange={(e) => onNewsSourceChange(e.target.value)}>
                    <option value="manual_submit">manual_submit</option>
                    <option value="AgroMonitor">AgroMonitor</option>
                    <option value="AGROINFO">AGROINFO</option>
                    <option value="VITIC">VITIC</option>
                    <option value="Vietstock">Vietstock</option>
                    <option value="CafeF">CafeF</option>
                    <option value="VNExpress">VNExpress</option>
                  </select>
                  <select value={newsForm.category} onChange={(e) => setNewsForm({ ...newsForm, category: e.target.value })}>
                    <option value="other">other</option>
                    <option value="agriculture">agriculture</option>
                    <option value="rice">rice</option>
                    <option value="seafood">seafood</option>
                    <option value="fx">fx</option>
                    <option value="logistics">logistics</option>
                    <option value="policy">policy</option>
                  </select>
                  <select value={newsForm.folder_type} onChange={(e) => setNewsForm({ ...newsForm, folder_type: e.target.value })}>
                    <option value="agriculture_news">Lưu folder: agriculture_news</option>
                    <option value="stock_news">Lưu folder: stock_news</option>
                  </select>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '2px 0 8px 0', lineHeight: 1.4 }}>
                    Gợi ý tự động theo nguồn: {newsForm.source} → {newsForm.folder_type} / {newsForm.category}
                  </div>
                  <button type="submit" className="timeframe-btn active" style={{ marginTop: 8 }}>Submit tin</button>
                  <div style={{ marginTop: 8, color: 'var(--text-secondary)' }}>{newsStatus}</div>
                </form>
                <div className="panel-header" style={{ margin: '0 0 8px 0' }}>Lịch sử submit tin</div>
                <div style={{ overflowX: 'auto', border: '1px solid var(--border-color)' }}>
                  {newsHistoryLoading ? <div style={{ padding: 12 }}>Đang tải...</div> : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Thời gian</th>
                        <th>Tiêu đề</th>
                        <th>Nguồn</th>
                        <th>Folder</th>
                        <th style={{ width: 72 }} />
                      </tr>
                    </thead>
                    <tbody>
                      {newsHistory.length === 0 && (
                        <tr><td colSpan={5} style={{ padding: 12, color: 'var(--text-secondary)' }}>Chưa có bản ghi.</td></tr>
                      )}
                      {newsHistory.map((row) => (
                        <tr key={row.id}>
                          <td style={{ whiteSpace: 'nowrap', fontSize: 10 }}>{row.submitted_at ? String(row.submitted_at).replace('T', ' ').slice(0, 19) : ''}</td>
                          <td style={{ fontSize: 11 }}>
                            <a href={row.link} target="_blank" rel="noreferrer" className="news-title">{row.title}</a>
                          </td>
                          <td style={{ fontSize: 10 }}>{row.source}</td>
                          <td style={{ fontSize: 10 }}>{row.folder_type}</td>
                          <td>
                            <button type="button" className="timeframe-btn" style={{ fontSize: 9, padding: '2px 6px' }} onClick={() => deleteNewsHistoryRow(row.id)}>Xóa</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  )}
                </div>
              </div>
              )}
            </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function App() {
  const isSubmitPage = window.location.pathname === '/submit';
  if (isSubmitPage) {
    return <SubmitPage />;
  }

  const [prices, setPrices] = useState([]);
  const [stocks, setStocks] = useState([]);
  const [stockNews, setStockNews] = useState([]);
  const [news, setNews] = useState([]);
  const [insights, setInsights] = useState({
    top_alerts: [],
    news_alerts: [],
    export_analytics: { period: '', top_markets: [], fob_cif_spread: [] }
  });
  const [loading, setLoading] = useState(true);
  const [nowTs, setNowTs] = useState(new Date());
  const [insightsSidebarTab, setInsightsSidebarTab] = useState('alerts');

  // Analytics State
  const [selectedCommodity, setSelectedCommodity] = useState("Tôm Sú (Black Tiger)");
  const [timeframe, setTimeframe] = useState("30d");
  const [historyData, setHistoryData] = useState({ labels: [], prices: [] });

  useEffect(() => {
    const fetchCoreData = async () => {
      try {
        const [priceRes, stockRes, newsRes, insightsRes, stockNewsRes] = await Promise.all([
          axios.get(`${API_BASE}/prices`),
          axios.get(`${API_BASE}/stocks`),
          axios.get(`${API_BASE}/news`),
          axios.get(`${API_BASE}/insights/dashboard`),
          axios.get(`${API_BASE}/stocks/news`)
        ]);
        setPrices(priceRes.data.data);
        setStocks(stockRes.data.data);
        setNews(newsRes.data.data);
        setStockNews(stockNewsRes?.data?.data || []);
        if (insightsRes?.data?.status === 'success') {
          setInsights(insightsRes.data.data);
        }
        setLoading(false);
      } catch (err) {
        console.error("Fetch error", err);
        setLoading(false);
      }
    };
    fetchCoreData();
    // Simulate real-time ticks
    const interval = setInterval(fetchCoreData, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNowTs(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await axios.get(`${API_BASE}/history/${encodeURIComponent(selectedCommodity)}?range=${timeframe}`);
        if(res.data.status === 'success') {
           setHistoryData(res.data.data);
        }
      } catch(e) { console.error("History fetch error", e); }
    };
    if (selectedCommodity) {
      fetchHistory();
    }
  }, [selectedCommodity, timeframe]);

  const chartData = {
    labels: historyData.labels,
    datasets: [{
      fill: true, label: `${selectedCommodity}`, data: historyData.prices,
      borderColor: '#00ff41', backgroundColor: 'rgba(0, 255, 65, 0.1)', 
      tension: 0.1, borderWidth: 1.5, pointRadius: 0, pointHitRadius: 10
    }]
  };

  const chartOptions = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
    scales: {
      x: { grid: { color: '#222' }, ticks: { color: '#888', font: { family: 'SFMono-Regular', size: 10 } } },
      y: { grid: { color: '#222' }, ticks: { color: '#00ff41', font: { family: 'SFMono-Regular', size: 10 } }, position: 'right' }
    },
    interaction: { mode: 'nearest', axis: 'x', intersect: false }
  };

  const seafoodNames = ["Tôm Sú (Black Tiger)", "Tôm Thẻ (Vannamei)", "Cá Ba Sa (Pangasius)", "Cua Thịt (Mud Crab)", "Cua Gạch (Egg Crab)"];
  const isSeafood = (name = '') => {
    const n = name.toLowerCase();
    return seafoodNames.includes(name) || n.includes('tôm') || n.includes('cá') || n.includes('cua');
  };
  const isRice = (name = '') => {
    const n = name.toLowerCase();
    return n.includes('lúa') || n.includes('gạo') || n.includes('rice');
  };
  const vnSeafood = prices.filter(p => isSeafood(p.name));
  const vnRice = prices.filter(p => isRice(p.name));
  const vnAgri = prices.filter(p => !isSeafood(p.name) && !isRice(p.name));

  const findByName = (name) => prices.find((p) => p.name === name);
  const ir504 = findByName("Lúa Thường (IR50404)") || vnRice.find((p) => p.name.toLowerCase().includes('lúa'));
  const rice5 = findByName("Gạo Xuất Khẩu 5%") || vnRice.find((p) => p.name.toLowerCase().includes('gạo'));
  const blackTiger = findByName("Tôm Sú (Black Tiger)");
  const pangasius = findByName("Cá Ba Sa (Pangasius)");
  const exportTop = insights.export_analytics?.top_markets || [];
  const exportSpread = insights.export_analytics?.fob_cif_spread?.[0];
  const exportDelta = typeof exportSpread?.delta_pct === 'number' ? exportSpread.delta_pct : 0;
  const exportTrend = exportDelta >= 0 ? 'up' : 'down';
  const exportValue = exportSpread && exportSpread.from_price !== 'N/A'
    ? `${exportSpread.from_price} → ${exportSpread.to_price} ${exportSpread.unit}`
    : 'Đang cập nhật';
  const topMarketsValue = exportTop.length
    ? exportTop.slice(0, 3).map((x) => x.replace(/^\d+\.\s*/, '')).join(' | ')
    : 'Đang cập nhật';

  const summaryRows = [
    {
      key: 'ir504',
      group: 'agri',
      title: 'Giá lúa IR504',
      item: ir504,
      value: ir504 ? `${Math.round(ir504.price).toLocaleString()} VND/kg` : 'N/A'
    },
    {
      key: 'black-tiger',
      group: 'seafood',
      title: 'Giá tôm sú',
      item: blackTiger,
      value: blackTiger ? `${Math.round(blackTiger.price).toLocaleString()} VND/kg` : 'N/A'
    },
    {
      key: 'export',
      group: 'all',
      title: 'Kim ngạch XNK tháng',
      item: { trend: exportTrend, change_pct: exportDelta },
      value: exportValue
    },
    {
      key: 'rice5',
      group: 'agri',
      title: 'Giá gạo 5%',
      item: rice5,
      value: rice5 ? `${Math.round(rice5.price * 1000).toLocaleString()} VND/tấn` : 'N/A'
    },
    {
      key: 'pangasius',
      group: 'seafood',
      title: 'Giá cá tra',
      item: pangasius,
      value: pangasius ? `${Math.round(pangasius.price).toLocaleString()} VND/kg` : 'N/A'
    },
    {
      key: 'markets',
      group: 'all',
      title: 'Top thị trường',
      item: { trend: exportTop.length ? 'up' : 'down', change_pct: 0 },
      value: topMarketsValue
    }
  ];

  const visibleSummaryRows = summaryRows;
  const sortedStocks = [...stocks].sort((a, b) => Math.abs(b?.change_pct ?? 0) - Math.abs(a?.change_pct ?? 0));

  const topAlerts = insights.top_alerts || [];
  const rightAlerts = insights.news_alerts || [];
  const exportTopMarkets = insights.export_analytics?.top_markets || [];
  const fobCifSpread = insights.export_analytics?.fob_cif_spread || [];

  return (
    <div className="dashboard-container">
      <header className="site-header">
        <div className="brand-block">
          <img src="/favicon.svg" alt="" className="brand-icon" width={22} height={22} />
          <span className="brand-name">TDI Agriculture Monitor</span>
          <span className="brand-beta">BETA</span>
        </div>
        <div className="brand-meta">
          <span>{nowTs.toLocaleString('vi-VN')}</span>
          <a href="/submit" rel="noreferrer">
            <Upload size={12} strokeWidth={2} aria-hidden />
            Submit data
          </a>
          <a href="https://www.facebook.com/trandaopath" target="_blank" rel="noreferrer">Follow us on Facebook</a>
        </div>
      </header>

      {/* Ticker Tape */}
      <div className="ticker-tape">
        <div className="ticker-content">
          <span style={{color: 'var(--accent)', marginRight: '20px'}}>LIVE MARKETS | </span>
          {stocks.map((s, i) => (
            <span key={i}>
              {s.symbol} <span className={s.trend === 'up' ? 'text-up' : 'text-down'}>{s.price} {s.trend === 'up' ? '▲' : '▼'}{Math.abs(s.change_pct)}%</span>
            </span>
          ))}
          <span style={{color: 'var(--accent)', marginRight: '20px', marginLeft: '40px'}}>COMMODITIES | </span>
          {prices.map((p, i) => (
            <span key={`p${i}`}>
              {p.name.split(' ')[0]} <span className={p.trend === 'up' ? 'text-up' : 'text-down'}>{p.price.toLocaleString()} {p.trend === 'up' ? '▲' : '▼'}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="main-grid">
        {/* Left Column: Commodities */}
        <div className="panel col-left">
          <div className="panel-header">
            <span>TỔNG HỢP NHANH</span>
          </div>
          <div className="panel-content summary-section" style={{ flex: 'none', padding: '6px', borderBottom: '1px solid var(--border-color)' }}>
            <div className="summary-grid">
              {visibleSummaryRows.map((card) => {
                const isUp = card.item?.trend !== 'down';
                const pct = card.item?.change_pct ?? 0;
                return (
                  <div key={card.key} className="summary-card">
                    <div className="summary-title">{card.title}</div>
                    <div className={`summary-change ${isUp ? 'text-up' : 'text-down'}`}>
                      {pct > 0 ? '+' : ''}{pct}% {isUp ? '▲' : '▼'}
                    </div>
                    <div className="summary-value">{card.value}</div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="panel-header"><Activity size={14} /> THỦY SẢN (SEAFOOD)</div>
          <div className="panel-content" style={{ padding: 0, flex: 'none', borderBottom: '1px solid var(--border-color)' }}>
            <table className="data-table">
              <thead><tr><th>Product</th><th style={{textAlign: 'right'}}>Chg</th><th style={{textAlign: 'right'}}>Last (VND)</th></tr></thead>
              <tbody>
                {vnSeafood.map((p, i) => (
                  <tr key={i} className={selectedCommodity === p.name ? 'active-row' : ''} onClick={() => setSelectedCommodity(p.name)}>
                    <td>{p.name}</td>
                    <td className={`heatmap-change ${p.trend === 'up' ? 'text-up' : 'text-down'}`}>
                      {p.change_pct > 0 ? '+' : ''}{p.change_pct}%
                    </td>
                    <td style={{textAlign: 'right', fontWeight: 'bold'}}>{p.price.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel-header" style={{ borderTop: 'none' }}><Wheat size={14} /> LÚA GẠO (RICE)</div>
          <div className="panel-content" style={{ padding: 0, flex: 'none', borderBottom: '1px solid var(--border-color)' }}>
            <table className="data-table">
              <thead><tr><th>Product</th><th style={{textAlign: 'right'}}>Chg</th><th style={{textAlign: 'right'}}>Last (VND)</th></tr></thead>
              <tbody>
                {vnRice.map((p, i) => (
                  <tr key={`rice-${i}`} className={selectedCommodity === p.name ? 'active-row' : ''} onClick={() => setSelectedCommodity(p.name)}>
                    <td>{p.name}</td>
                    <td className={`heatmap-change ${p.trend === 'up' ? 'text-up' : 'text-down'}`}>
                      {p.change_pct > 0 ? '+' : ''}{p.change_pct}%
                    </td>
                    <td style={{textAlign: 'right', fontWeight: 'bold'}}>{p.price.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel-header" style={{ borderTop: 'none', position: 'sticky', top: 0, zIndex: 2 }}><Sprout size={14} /> NÔNG SẢN KHÁC (AGRICULTURE)</div>
          <div className="panel-content" style={{ padding: 0 }}>
            <table className="data-table">
              <thead><tr><th>Product</th><th style={{textAlign: 'right'}}>Chg</th><th style={{textAlign: 'right'}}>Last (VND)</th></tr></thead>
              <tbody>
                {vnAgri.map((p, i) => (
                  <tr key={i} className={selectedCommodity === p.name ? 'active-row' : ''} onClick={() => setSelectedCommodity(p.name)}>
                    <td>{p.name}</td>
                    <td className={`heatmap-change ${p.trend === 'up' ? 'text-up' : 'text-down'}`}>
                      {p.change_pct > 0 ? '+' : ''}{p.change_pct}%
                    </td>
                    <td style={{textAlign: 'right', fontWeight: 'bold'}}>{p.price.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

        </div>

        {/* Center Column: Chart & Stocks */}
        <div className="col-center">
          <div className="panel" style={{ flex: 1.65 }}>
            <div className="panel-header">
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><BarChart2 size={14} /> {selectedCommodity} - Spot Prices</span>
              <div className="timeframe-group">
                {['1d', '7d', '30d', '6m', '1y'].map(tf => (
                  <button key={tf} className={`timeframe-btn ${timeframe === tf ? 'active' : ''}`} onClick={() => setTimeframe(tf)}>{tf.toUpperCase()}</button>
                ))}
              </div>
            </div>
            <div className="chart-container">
              <div style={{ position: 'relative', width: '100%', height: '100%' }}>
                <Line data={chartData} options={chartOptions} />
              </div>
            </div>
          </div>

          <div className="panel" style={{ flex: 1.35, borderTop: '1px solid var(--border-color)' }}>
            <div className="panel-header">Aquaculture Equities Monitor</div>
            <div className="panel-content equities-panel-split" style={{ overflow: 'hidden', padding: '6px' }}>
              <div className="heatmap-grid equities-grid">
                {sortedStocks.map((s, i) => (
                  <div key={i} className={`heatmap-item ${s.trend}`}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <a href={s?.links?.fireant || '#'} target="_blank" rel="noreferrer" className="heatmap-symbol-link">
                        <span className="heatmap-symbol">{s.symbol}</span>
                      </a>
                      <span style={{ fontSize: '10px', opacity: 0.8 }}>{s.currency}</span>
                    </div>
                    <div className="heatmap-price">{s.price.toFixed(2)}</div>
                    <div className="heatmap-change">
                      {s.change_pct > 0 ? '+' : ''}{s.change_pct}% ({s.change_amt})
                    </div>
                  </div>
                ))}
              </div>
              <div className="stock-news-box">
                <div className="panel-header right-sub-header">Stock News</div>
                <div className="stock-news-list">
                  {stockNews.map((item, idx) => (
                    <div key={idx} className="news-item" style={{ padding: '6px 8px' }}>
                      <div className="news-meta">
                        <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{item.source}</span>
                      </div>
                      <a href={item.link} target="_blank" rel="noreferrer" className="news-title" style={{ fontSize: '11px' }}>
                        {item.title}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Market Insights (top) + News & Alerts */}
        <div className="panel col-right">
          <div className="insights-sidebar">
            <div className="insights-tab-row" role="tablist" aria-label="Market insights">
              <button
                type="button"
                role="tab"
                aria-selected={insightsSidebarTab === 'alerts'}
                className={`insights-tab${insightsSidebarTab === 'alerts' ? ' is-active' : ''}`}
                onClick={() => setInsightsSidebarTab('alerts')}
              >
                <span className="insights-tab-icon">🧠</span>
                <span>Insights</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={insightsSidebarTab === 'export'}
                className={`insights-tab${insightsSidebarTab === 'export' ? ' is-active' : ''}`}
                onClick={() => setInsightsSidebarTab('export')}
              >
                <span className="insights-tab-icon">📦</span>
                <span>Export</span>
              </button>
            </div>
            <div className="insights-sidebar-inner">
              {insightsSidebarTab === 'alerts' && (
                <div className="alert-topbar right-alert-topbar insights-tab-panel" role="tabpanel">
                  {topAlerts.map((a, idx) => (
                    <span key={idx} className={`risk-pill ${a.level}`}>{a.text}</span>
                  ))}
                </div>
              )}
              {insightsSidebarTab === 'export' && (
                <div className="export-box insights-export-box insights-tab-panel" role="tabpanel">
                  <div className="export-title">Top 5 thị trường ({insights.export_analytics?.period || 'N/A'}):</div>
                  {exportTopMarkets.map((line, i) => (
                    <div key={i} className="export-line">{line}</div>
                  ))}
                  <div className="export-gap" />
                  <div className="export-title">FOB vs CIF Spread:</div>
                  {fobCifSpread.map((row, i) => (
                    <div key={i} className="export-line">
                      {row.label}: {row.from_price} → {row.to_price} {row.unit} ({row.delta_pct > 0 ? '+' : ''}{row.delta_pct}%)
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="panel-header"><Clock size={14} /> News & Alerts</div>
          <div className="panel-content right-panel-block col-right-news-block" style={{ padding: 8 }}>
            <div className="alerts-box">
              {rightAlerts.map((a, i) => (
                <div key={i} className="alerts-row">
                  <span>{a.icon}</span>
                  {a.link ? (
                    <a href={a.link} target="_blank" rel="noreferrer" className="alerts-link">
                      {a.text}
                    </a>
                  ) : (
                    <span>{a.text}</span>
                  )}
                </div>
              ))}
            </div>

            <div className="panel-header right-sub-header">
              <span className="sub-header-icon">📰</span>
              <span className="sub-header-title">LIVE TERMINAL FEED (HIGH-VOLUME)</span>
            </div>
            <div className="news-list-box">
              {loading ? <div style={{padding: '10px'}}>Connecting to data stream...</div> : news.map((item, idx) => (
                <div key={idx} className="news-item" style={{ gap: '4px', padding: '6px 8px' }}>
                  <div className="news-meta">
                    <span style={{ color: 'var(--text-secondary)' }}>[{item.date.split(' ')[0]}]</span>
                    <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{item.source}</span>
                  </div>
                  <a href={item.link} target="_blank" rel="noreferrer" className="news-title" style={{ fontSize: '11px', whiteSpace: 'normal' }}>
                    {item.title}
                  </a>
                </div>
              ))}
            </div>
          </div>
        </div>

      </div>

      <footer className="site-footer">
        <span>© {new Date().getFullYear()} TRANDAO Investment. All rights reserved.</span>
      </footer>
    </div>
  );
}

export default App;
