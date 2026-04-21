import { useState } from 'react';
import { Table, Modal } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { RankItem } from '../../api/funding';
import { fundingApi } from '../../api/funding';

interface RankTableProps {
  data: RankItem[];
  loading: boolean;
  onDiffClick: (record: RankItem) => void;
  onWatchToggle?: (coin: string, longEx: string, shortEx: string) => void;
}

const exLabel: Record<string, string> = { BN: 'BN', OKX: 'OKX', BY: 'BY' };

export default function RankTable({ data, loading, onDiffClick, onWatchToggle }: RankTableProps) {
  const [indexModal, setIndexModal] = useState<{ coin: string; long_exchange: string; short_exchange: string } | null>(null);
  const [indexDetail, setIndexDetail] = useState<{ exchange: string; long_weight: number; short_weight: number; common: boolean }[] | null>(null);

  const showIndexDetail = async (record: RankItem) => {
    setIndexModal({ coin: record.coin, long_exchange: record.long_exchange, short_exchange: record.short_exchange });
    try {
      const res = await fundingApi.getIndexDetail(record.coin, record.long_exchange, record.short_exchange);
      setIndexDetail(res.data);
    } catch {
      setIndexDetail([]);
    }
  };

  const columns: ColumnsType<RankItem> = [
    {
      title: '',
      key: 'watch',
      width: 36,
      fixed: 'left',
      render: (_, r) => (
        <span
          onClick={(e) => { e.stopPropagation(); onWatchToggle?.(r.coin, r.long_exchange, r.short_exchange); }}
          style={{ cursor: 'pointer', fontSize: 16, color: r.watched ? '#faad14' : '#e0e0e0' }}
        >
          {r.watched ? '★' : '☆'}
        </span>
      ),
    },
    {
      title: '币种',
      dataIndex: 'coin',
      key: 'coin',
      width: 72,
      fixed: 'left',
      render: (coin: string) => (
        <a href={`https://www.coinglass.com/tv/zh/Binance_${coin}USDT`} target="_blank" rel="noopener noreferrer">
          {coin}
        </a>
      ),
    },
    {
      title: '做多总资费',
      key: 'long_funding_ex',
      width: 105,
      render: (_, r) => (
        <span style={{ color: r.long_total_funding >= 0 ? '#22AB94' : '#F23645' }}>
          {r.long_total_funding >= 0 ? '+' : ''}{r.long_total_funding.toFixed(2)}%
          <span style={{ color: '#999', marginLeft: 3, fontSize: 11 }}>{exLabel[r.long_exchange] || r.long_exchange}</span>
        </span>
      ),
    },
    {
      title: '做空总资费',
      key: 'short_funding_ex',
      width: 105,
      sorter: (a, b) => a.short_total_funding - b.short_total_funding,
      render: (_, r) => (
        <span style={{ color: r.short_total_funding >= 0 ? '#22AB94' : '#F23645' }}>
          {r.short_total_funding >= 0 ? '+' : ''}{r.short_total_funding.toFixed(2)}%
          <span style={{ color: '#999', marginLeft: 3, fontSize: 11 }}>{exLabel[r.short_exchange] || r.short_exchange}</span>
        </span>
      ),
    },
    {
      title: '资费差额',
      dataIndex: 'total_diff',
      key: 'total_diff',
      width: 80,
      sorter: (a, b) => a.total_diff - b.total_diff,
      defaultSortOrder: 'descend',
      render: (val: number, record: RankItem) => (
        <span onClick={() => onDiffClick(record)} style={{ color: val >= 0 ? '#22AB94' : '#F23645', cursor: 'pointer' }}>
          {val >= 0 ? '+' : ''}{val.toFixed(2)}%
        </span>
      ),
    },
    {
      title: '做多结算',
      key: 'long_count_period',
      width: 75,
      render: (_, r) => (
        <span>{r.long_settlement_count}次<span style={{ color: '#999' }}>/{r.long_settlement_period}h</span></span>
      ),
    },
    {
      title: '做空结算',
      key: 'short_count_period',
      width: 75,
      render: (_, r) => (
        <span>{r.short_settlement_count}次<span style={{ color: '#999' }}>/{r.short_settlement_period}h</span></span>
      ),
    },
    {
      title: '1d涨幅',
      dataIndex: 'change_1d',
      key: 'change_1d',
      width: 70,
      sorter: (a, b) => (a.change_1d ?? 0) - (b.change_1d ?? 0),
      render: (val?: number) =>
        val !== undefined
          ? <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}%</span>
          : <span style={{ color: '#d9d9d9' }}>—</span>,
    },
    {
      title: '3d涨幅',
      dataIndex: 'change_3d',
      key: 'change_3d',
      width: 70,
      sorter: (a, b) => (a.change_3d ?? 0) - (b.change_3d ?? 0),
      render: (val?: number) =>
        val !== undefined
          ? <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}%</span>
          : <span style={{ color: '#d9d9d9' }}>—</span>,
    },
    {
      title: '开差',
      dataIndex: 'current_spread',
      key: 'current_spread',
      width: 80,
      sorter: (a, b) => (a.current_spread ?? 0) - (b.current_spread ?? 0),
      render: (val?: number) =>
        val !== undefined
          ? <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}%</span>
          : <span style={{ color: '#d9d9d9' }}>-</span>,
    },
    {
      title: '基差',
      dataIndex: 'current_basis',
      key: 'current_basis',
      width: 80,
      sorter: (a, b) => (a.current_basis ?? 0) - (b.current_basis ?? 0),
      render: (val?: number) =>
        val !== undefined
          ? <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>{val >= 0 ? '+' : ''}{val.toFixed(2)}%</span>
          : <span style={{ color: '#d9d9d9' }}>-</span>,
    },
    {
      title: '持仓量',
      dataIndex: 'oi',
      key: 'oi',
      width: 82,
      sorter: (a, b) => (a.oi ?? 0) - (b.oi ?? 0),
      render: (val?: number) =>
        val ? <span style={{ color: val < 3e6 ? '#F23645' : val > 10e6 ? '#22AB94' : undefined }}>{(val / 1e6).toFixed(2)}m</span> : <span style={{ color: '#d9d9d9' }}>—</span>,
    },
    {
      title: '多空比',
      dataIndex: 'lsr',
      key: 'lsr',
      width: 70,
      sorter: (a, b) => (a.lsr ?? 0) - (b.lsr ?? 0),
      render: (val?: number) =>
        val
          ? <span style={{ color: val < 1 ? '#22AB94' : undefined }}>{val.toFixed(2)}</span>
          : <span style={{ color: '#d9d9d9' }}>—</span>,
    },
    {
      title: 'bn_spot',
      dataIndex: 'bn_spot',
      key: 'bn_spot',
      width: 65,
      render: (val?: boolean) =>
        val
          ? <span style={{ color: '#22AB94', fontSize: 15 }}>&#10003;</span>
          : <span style={{ color: '#d9d9d9', fontSize: 13 }}>&#10007;</span>,
    },
    {
      title: '价格趋势',
      key: 'trend',
      width: 85,
      sorter: (a, b) => {
        const score = (r: RankItem) => (r.trend_daily ? 8 : 0) + (r.trend_h4 ? 4 : 0) + (r.trend_h1 ? 2 : 0) + (r.trend_m15 ? 1 : 0);
        return score(a) - score(b);
      },
      render: (_, record) => (
        <span style={{ display: 'flex', gap: 3 }} title="日线 4H 1H 15m">
          {[record.trend_daily, record.trend_h4, record.trend_h1, record.trend_m15].map((v, i) => (
            <span key={i} style={{
              display: 'inline-block', width: 11, height: 11, borderRadius: '50%',
              backgroundColor: v ? '#22AB94' : '#e0e0e0',
            }} />
          ))}
        </span>
      ),
    },
    {
      title: 'bn_alpha',
      dataIndex: 'bn_alpha',
      key: 'bn_alpha',
      width: 75,
      sorter: (a, b) => (a.bn_alpha ?? 0) - (b.bn_alpha ?? 0),
      render: (val?: number) =>
        val ? <span style={{ color: '#E6A700' }}>{(val * 100).toFixed(1)}%</span> : <span style={{ color: '#d9d9d9' }}>—</span>,
    },
    {
      title: 'bn_future',
      dataIndex: 'bn_future',
      key: 'bn_future',
      width: 75,
      sorter: (a, b) => (a.bn_future ?? 0) - (b.bn_future ?? 0),
      render: (val?: number) =>
        val ? <span style={{ color: '#E6A700' }}>{(val * 100).toFixed(1)}%</span> : <span style={{ color: '#d9d9d9' }}>—</span>,
    },
    {
      title: '共同指数',
      dataIndex: 'index_overlap',
      key: 'index_overlap',
      width: 80,
      sorter: (a, b) => (a.index_overlap ?? 0) - (b.index_overlap ?? 0),
      render: (val: number | undefined, record: RankItem) =>
        val !== undefined && val > 0 ? (
          <span
            onClick={(e) => { e.stopPropagation(); showIndexDetail(record); }}
            style={{ color: '#1677ff', cursor: 'pointer' }}
          >
            {(val * 100).toFixed(1)}%
          </span>
        ) : (
          <span
            onClick={(e) => { e.stopPropagation(); showIndexDetail(record); }}
            style={{ color: '#d9d9d9', cursor: 'pointer' }}
          >0%</span>
        ),
    },
  ];

  return (
    <>
    <Table<RankItem>
      columns={columns}
      dataSource={data}
      loading={loading}
      rowKey={(record) => `${record.coin}_${record.long_exchange}_${record.short_exchange}`}
      pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
      size="small"
      scroll={{ x: 1600 }}
      style={{ fontSize: 13 }}
    />
    <Modal
      title={indexModal ? `${indexModal.coin} 指数成分（${exLabel[indexModal.long_exchange] || indexModal.long_exchange} vs ${exLabel[indexModal.short_exchange] || indexModal.short_exchange}）` : ''}
      open={!!indexModal}
      onCancel={() => setIndexModal(null)}
      footer={null}
      width={600}
    >
      {indexDetail && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #eee', textAlign: 'left' }}>
              <th style={{ padding: '6px 8px' }}>交易所</th>
              <th style={{ padding: '6px 8px' }}>做多方权重</th>
              <th style={{ padding: '6px 8px' }}>做空方权重</th>
              <th style={{ padding: '6px 8px' }}>共同</th>
            </tr>
          </thead>
          <tbody>
            {indexDetail.map((row, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #f0f0f0', backgroundColor: row.common ? '#f6ffed' : undefined }}>
                <td style={{ padding: '5px 8px' }}>{row.exchange}</td>
                <td style={{ padding: '5px 8px' }}>{row.long_weight ? (row.long_weight * 100).toFixed(2) + '%' : '—'}</td>
                <td style={{ padding: '5px 8px' }}>{row.short_weight ? (row.short_weight * 100).toFixed(2) + '%' : '—'}</td>
                <td style={{ padding: '5px 8px', color: row.common ? '#22AB94' : '#d9d9d9' }}>{row.common ? '✓' : '✗'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
    </>
  );
}
