import { useState, useEffect } from 'react';
import { Modal, Form, Select, DatePicker, Button, Table, Descriptions, Tabs, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { fundingApi, type FundingDetail, type DaySummary, type CalculatorResult } from '../../api/funding';

const { RangePicker } = DatePicker;

export interface CalcInitialValues {
  coin: string;
  longExchange: string;
  shortExchange: string;
  timeRange: [Dayjs, Dayjs];
}

interface CalculatorProps {
  open: boolean;
  onClose: () => void;
  initialValues?: CalcInitialValues;
}

const exchangeOptions = [
  { label: 'Binance (BN)', value: 'BN' },
  { label: 'OKX', value: 'OKX' },
  { label: 'Bybit (BY)', value: 'BY' },
];

export default function Calculator({ open, onClose, initialValues }: CalculatorProps) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CalculatorResult | null>(null);
  const [coins, setCoins] = useState<{ label: string; value: string }[]>([]);
  const [autoTriggered, setAutoTriggered] = useState(false);

  useEffect(() => {
    if (open) {
      fundingApi.getCoins().then((list) => {
        setCoins(list.map((c) => ({ label: c, value: c })));
      }).catch(() => {});
      setAutoTriggered(false);
    }
  }, [open]);

  const handleCalculate = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      const [startTime, endTime] = values.timeRange as [Dayjs, Dayjs];
      const start = startTime.valueOf();
      const end = endTime.valueOf();

      const res = await fundingApi.calculate(
        values.coin.toUpperCase(),
        values.longExchange,
        values.shortExchange,
        start,
        end,
      );
      setResult(res.data);
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error('计算失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  // Auto-calculate when opened with initialValues from diff click
  useEffect(() => {
    if (open && initialValues && !autoTriggered) {
      form.setFieldsValue({
        coin: initialValues.coin,
        longExchange: initialValues.longExchange,
        shortExchange: initialValues.shortExchange,
        timeRange: initialValues.timeRange,
      });
      setAutoTriggered(true);
      setTimeout(() => handleCalculate(), 0);
    }
  }, [open, initialValues, autoTriggered]);

  const periodColumns: ColumnsType<FundingDetail> = [
    {
      title: '结算时间',
      dataIndex: 'time',
      key: 'time',
      width: 180,
      render: (val: number) => dayjs(val).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '做多方资费',
      dataIndex: 'long_funding',
      key: 'long_funding',
      width: 120,
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
      title: '做空方资费',
      dataIndex: 'short_funding',
      key: 'short_funding',
      width: 120,
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
      width: 100,
      render: (val: number) => (
        <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
          {val >= 0 ? '+' : ''}{val.toFixed(3)}%
        </span>
      ),
    },
  ];

  const renderFundingValue = (val: number) => (
    <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
      {val >= 0 ? '+' : ''}{val.toFixed(3)}%
    </span>
  );

  const dayColumns: ColumnsType<DaySummary> = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 120 },
    {
      title: '做多方合计',
      dataIndex: 'long_total',
      key: 'long_total',
      width: 120,
      render: (val: number) => renderFundingValue(val),
    },
    {
      title: '做空方合计',
      dataIndex: 'short_total',
      key: 'short_total',
      width: 120,
      render: (val: number) => renderFundingValue(val),
    },
    {
      title: '差额',
      dataIndex: 'diff',
      key: 'diff',
      width: 100,
      render: (val: number) => renderFundingValue(val),
    },
  ];

  // Append summary row to per_day data
  const dayDataWithSummary = result
    ? [
        ...result.per_day,
        {
          date: '总计',
          long_total: result.summary.long_total,
          short_total: result.summary.short_total,
          diff: result.summary.total_diff,
        },
      ]
    : [];

  const resultTabs = result
    ? [
        {
          key: 'day',
          label: '每日汇总',
          children: (
            <Table<DaySummary>
              columns={dayColumns}
              dataSource={dayDataWithSummary}
              rowKey="date"
              pagination={false}
              size="small"
              scroll={{ y: 400 }}
              rowClassName={(record) => (record.date === '总计' ? 'summary-row' : '')}
            />
          ),
        },
        {
          key: 'period',
          label: '每期明细',
          children: (
            <Table<FundingDetail>
              columns={periodColumns}
              dataSource={result.per_period}
              rowKey="time"
              pagination={{ pageSize: 100, showSizeChanger: true }}
              size="small"
              scroll={{ y: 400 }}
            />
          ),
        },
      ]
    : [];

  return (
    <Modal
      title="资费计算器"
      open={open}
      onCancel={() => {
        onClose();
        setResult(null);
        form.resetFields();
      }}
      footer={null}
      width={900}
      destroyOnClose
    >
      <style>{`.summary-row td { font-weight: bold !important; background: #fafafa !important; }`}</style>
      <Form form={form} layout="inline" style={{ marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Form.Item name="coin" label="币种" rules={[{ required: true, message: '请选择币种' }]}>
          <Select
            showSearch
            options={coins}
            placeholder="搜索币种"
            style={{ width: 140 }}
            filterOption={(input, option) =>
              (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>
        <Form.Item
          name="longExchange"
          label="做多交易所"
          rules={[{ required: true, message: '请选择' }]}
        >
          <Select options={exchangeOptions} style={{ width: 150 }} placeholder="选择交易所" />
        </Form.Item>
        <Form.Item
          name="shortExchange"
          label="做空交易所"
          rules={[{ required: true, message: '请选择' }]}
        >
          <Select options={exchangeOptions} style={{ width: 150 }} placeholder="选择交易所" />
        </Form.Item>
        <Form.Item
          name="timeRange"
          label="时间范围"
          rules={[{ required: true, message: '请选择时间范围' }]}
        >
          <RangePicker
            showTime={{ format: 'HH:00' }}
            format="YYYY-MM-DD HH:00"
            presets={[
              { label: '最近1天', value: [dayjs().subtract(1, 'day'), dayjs()] },
              { label: '最近2天', value: [dayjs().subtract(2, 'day'), dayjs()] },
              { label: '最近3天', value: [dayjs().subtract(3, 'day'), dayjs()] },
              { label: '最近7天', value: [dayjs().subtract(7, 'day'), dayjs()] },
              { label: '最近30天', value: [dayjs().subtract(30, 'day'), dayjs()] },
            ]}
          />
        </Form.Item>
        <Form.Item>
          <Button type="primary" onClick={handleCalculate} loading={loading}>
            计算
          </Button>
        </Form.Item>
      </Form>

      {result && <Tabs items={resultTabs} />}
    </Modal>
  );
}
