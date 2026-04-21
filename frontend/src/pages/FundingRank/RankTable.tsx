import { Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { RankItem } from '../../api/funding';

interface RankTableProps {
  data: RankItem[];
  loading: boolean;
  onDiffClick: (record: RankItem) => void;
}

const exchangeLabel: Record<string, string> = {
  BN: 'Binance',
  OKX: 'OKX',
  BY: 'Bybit',
};

export default function RankTable({ data, loading, onDiffClick }: RankTableProps) {
  const columns: ColumnsType<RankItem> = [
    {
      title: '币种',
      dataIndex: 'coin',
      key: 'coin',
      width: 90,
      fixed: 'left',
      render: (coin: string) => (
        <a
          href={`https://www.coinglass.com/tv/zh/Binance_${coin}USDT`}
          target="_blank"
          rel="noopener noreferrer"
        >
          {coin}
        </a>
      ),
    },
    {
      title: '做多总资费/交易所',
      key: 'long_funding_ex',
      width: 170,
      render: (_, record) => (
        <span style={{ color: record.long_total_funding >= 0 ? '#22AB94' : '#F23645' }}>
          {record.long_total_funding >= 0 ? '+' : ''}
          {record.long_total_funding.toFixed(3)}%
          <span style={{ color: '#999', marginLeft: 4, fontSize: 12 }}>
            {exchangeLabel[record.long_exchange] || record.long_exchange}
          </span>
        </span>
      ),
    },
    {
      title: '做空总资费/交易所',
      key: 'short_funding_ex',
      width: 170,
      sorter: (a, b) => a.short_total_funding - b.short_total_funding,
      render: (_, record) => (
        <span style={{ color: record.short_total_funding >= 0 ? '#22AB94' : '#F23645' }}>
          {record.short_total_funding >= 0 ? '+' : ''}
          {record.short_total_funding.toFixed(3)}%
          <span style={{ color: '#999', marginLeft: 4, fontSize: 12 }}>
            {exchangeLabel[record.short_exchange] || record.short_exchange}
          </span>
        </span>
      ),
    },
    {
      title: '做多结算次数/周期',
      key: 'long_count_period',
      width: 140,
      align: 'center',
      render: (_, record) => (
        <span>
          {record.long_settlement_count}次
          <span style={{ color: '#999', marginLeft: 4 }}>/{record.long_settlement_period}h</span>
        </span>
      ),
    },
    {
      title: '做空结算次数/周期',
      key: 'short_count_period',
      width: 140,
      align: 'center',
      render: (_, record) => (
        <span>
          {record.short_settlement_count}次
          <span style={{ color: '#999', marginLeft: 4 }}>/{record.short_settlement_period}h</span>
        </span>
      ),
    },
    {
      title: '总资费差额',
      dataIndex: 'total_diff',
      key: 'total_diff',
      width: 120,
      sorter: (a, b) => a.total_diff - b.total_diff,
      defaultSortOrder: 'descend',
      render: (val: number, record: RankItem) => (
        <span
          onClick={() => onDiffClick(record)}
          style={{ color: val >= 0 ? '#22AB94' : '#F23645', cursor: 'pointer' }}
        >
          {val >= 0 ? '+' : ''}
          {val.toFixed(3)}%
        </span>
      ),
    },
    {
      title: '1d涨幅',
      dataIndex: 'change_1d',
      key: 'change_1d',
      width: 90,
      sorter: (a, b) => (a.change_1d ?? 0) - (b.change_1d ?? 0),
      render: (val?: number) =>
        val !== undefined ? (
          <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
            {val >= 0 ? '+' : ''}{val.toFixed(2)}%
          </span>
        ) : (
          <span style={{ color: '#d9d9d9' }}>—</span>
        ),
    },
    {
      title: '3d涨幅',
      dataIndex: 'change_3d',
      key: 'change_3d',
      width: 90,
      sorter: (a, b) => (a.change_3d ?? 0) - (b.change_3d ?? 0),
      render: (val?: number) =>
        val !== undefined ? (
          <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
            {val >= 0 ? '+' : ''}{val.toFixed(2)}%
          </span>
        ) : (
          <span style={{ color: '#d9d9d9' }}>—</span>
        ),
    },
    {
      title: '开差',
      dataIndex: 'current_spread',
      key: 'current_spread',
      width: 90,
      sorter: (a, b) => (a.current_spread ?? 0) - (b.current_spread ?? 0),
      render: (val?: number) =>
        val !== undefined ? (
          <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
            {val >= 0 ? '+' : ''}
            {val.toFixed(4)}%
          </span>
        ) : (
          '-'
        ),
    },
    {
      title: '基差',
      dataIndex: 'current_basis',
      key: 'current_basis',
      width: 90,
      sorter: (a, b) => (a.current_basis ?? 0) - (b.current_basis ?? 0),
      render: (val?: number) =>
        val !== undefined ? (
          <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
            {val >= 0 ? '+' : ''}
            {val.toFixed(4)}%
          </span>
        ) : (
          '-'
        ),
    },
    {
      title: 'bn_alpha',
      dataIndex: 'bn_alpha',
      key: 'bn_alpha',
      width: 95,
      sorter: (a, b) => (a.bn_alpha ?? 0) - (b.bn_alpha ?? 0),
      render: (val?: number) =>
        val ? (
          <span style={{ color: '#E6A700' }}>{(val * 100).toFixed(1)}%</span>
        ) : (
          <span style={{ color: '#d9d9d9' }}>—</span>
        ),
    },
    {
      title: 'bn_future',
      dataIndex: 'bn_future',
      key: 'bn_future',
      width: 95,
      sorter: (a, b) => (a.bn_future ?? 0) - (b.bn_future ?? 0),
      render: (val?: number) =>
        val ? (
          <span style={{ color: '#E6A700' }}>{(val * 100).toFixed(1)}%</span>
        ) : (
          <span style={{ color: '#d9d9d9' }}>—</span>
        ),
    },
    {
      title: 'bn_spot',
      dataIndex: 'bn_spot',
      key: 'bn_spot',
      width: 80,
      align: 'center',
      filters: [
        { text: '有现货', value: true },
        { text: '无现货', value: false },
      ],
      onFilter: (value, record) => (record.bn_spot ?? false) === value,
      render: (val?: boolean) =>
        val ? (
          <span style={{ color: '#22AB94', fontSize: 16 }}>&#10003;</span>
        ) : (
          <span style={{ color: '#d9d9d9', fontSize: 14 }}>&#10007;</span>
        ),
    },
  ];

  return (
    <Table<RankItem>
      columns={columns}
      dataSource={data}
      loading={loading}
      rowKey={(record) => `${record.coin}_${record.long_exchange}_${record.short_exchange}`}
      pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
      size="small"
      scroll={{ x: 1280 }}
    />
  );
}
