import { Modal, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import type { FundingDetail } from '../../api/funding';

interface DetailModalProps {
  open: boolean;
  onClose: () => void;
  loading: boolean;
  data: FundingDetail[];
  coin: string;
  longExchange: string;
  shortExchange: string;
}

export default function DetailModal({
  open,
  onClose,
  loading,
  data,
  coin,
  longExchange,
  shortExchange,
}: DetailModalProps) {
  const columns: ColumnsType<FundingDetail> = [
    {
      title: '结算时间',
      dataIndex: 'time',
      key: 'time',
      width: 180,
      render: (val: number) => dayjs(val).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: `${longExchange}所收的资费`,
      dataIndex: 'long_funding',
      key: 'long_funding',
      width: 160,
      render: (val: number | null) =>
        val === null ? (
          <span style={{ color: '#d9d9d9' }}>—</span>
        ) : (
          <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
            {val >= 0 ? '+' : ''}{val.toFixed(3)}%
          </span>
        ),
    },
    {
      title: `${shortExchange}所付的资费`,
      dataIndex: 'short_funding',
      key: 'short_funding',
      width: 160,
      render: (val: number | null) =>
        val === null ? (
          <span style={{ color: '#d9d9d9' }}>—</span>
        ) : (
          <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
            {val >= 0 ? '+' : ''}{val.toFixed(3)}%
          </span>
        ),
    },
    {
      title: '差额',
      dataIndex: 'diff',
      key: 'diff',
      width: 120,
      render: (val: number) => (
        <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
          {val >= 0 ? '+' : ''}{val.toFixed(3)}%
        </span>
      ),
    },
  ];

  return (
    <Modal
      title={`${coin} 资费明细 (${longExchange}多 ${shortExchange}空)`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={800}
      destroyOnClose
    >
      <Table<FundingDetail>
        columns={columns}
        dataSource={data}
        loading={loading}
        rowKey="time"
        pagination={{ pageSize: 20, showSizeChanger: true }}
        size="small"
        scroll={{ y: 500 }}
      />
    </Modal>
  );
}
