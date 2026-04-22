import { useState, useEffect } from 'react';
import { Modal, Form, Select, DatePicker, Button, Table, Tabs, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { fundingApi, type CalculatorResult } from '../../api/funding';

const { RangePicker } = DatePicker;

export interface CalcInitialValues {
  coin: string;
  longExchange: string;
  shortExchange: string;
  timeRange?: [Dayjs, Dayjs];
}

interface CalculatorProps {
  open: boolean;
  onClose: () => void;
  initialValues?: CalcInitialValues;
}

const exchangeOptions = [
  { label: 'BN', value: 'BN' },
  { label: 'OKX', value: 'OKX' },
  { label: 'BY', value: 'BY' },
];

const exLabel: Record<string, string> = { BN: 'BN', OKX: 'OKX', BY: 'BY' };

const renderVal = (val: number | null | undefined) =>
  val !== null && val !== undefined ? (
    <span style={{ color: val >= 0 ? '#22AB94' : '#F23645' }}>
      {val >= 0 ? '+' : ''}{val.toFixed(3)}%
    </span>
  ) : <span style={{ color: '#d9d9d9' }}>—</span>;

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
      const res = await fundingApi.calculate(
        values.coin.toUpperCase(),
        values.longExchange,
        values.shortExchange,
        startTime.valueOf(),
        endTime.valueOf(),
        values.longExchange2 || undefined,
      );
      setResult(res.data);
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error('计算失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

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

  // Dynamic columns based on result
  const hasLong2 = !!(result?.long_exchange2);
  const l1 = exLabel[result?.long_exchange || ''] || result?.long_exchange || '做多1';
  const l2 = exLabel[result?.long_exchange2 || ''] || result?.long_exchange2 || '做多2';
  const s = exLabel[result?.short_exchange || ''] || result?.short_exchange || '做空';

  const periodColumns: ColumnsType<Record<string, any>> = [
    { title: '结算时间', dataIndex: 'time', key: 'time', width: 160,
      render: (val: number) => dayjs(val).format('YYYY-MM-DD HH:mm') },
    { title: `▲${l1}资费`, dataIndex: 'long1_funding', key: 'long1', width: 100, render: renderVal },
    ...(hasLong2 ? [{ title: `▲${l2}资费`, dataIndex: 'long2_funding', key: 'long2', width: 100, render: renderVal }] : []),
    { title: `▼${s}资费`, dataIndex: 'short_funding', key: 'short', width: 100, render: renderVal },
    { title: `${l1}_${s}差额`, dataIndex: 'diff1', key: 'diff1', width: 110, render: renderVal },
    ...(hasLong2 ? [{ title: `${l2}_${s}差额`, dataIndex: 'diff2', key: 'diff2', width: 110, render: renderVal }] : []),
  ];

  const dayColumns: ColumnsType<Record<string, any>> = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 110 },
    { title: `▲${l1}做多`, dataIndex: 'long1_total', key: 'long1', width: 110, render: renderVal },
    ...(hasLong2 ? [{ title: `▲${l2}做多`, dataIndex: 'long2_total', key: 'long2', width: 110, render: renderVal }] : []),
    { title: `▼${s}做空`, dataIndex: 'short_total', key: 'short', width: 110, render: renderVal },
    { title: `${l1}_${s}差额`, dataIndex: 'diff1', key: 'diff1', width: 110, render: renderVal },
    ...(hasLong2 ? [{ title: `${l2}_${s}差额`, dataIndex: 'diff2', key: 'diff2', width: 110, render: renderVal }] : []),
  ];

  const dayDataWithSummary = result
    ? [
        ...result.per_day,
        {
          date: '总计',
          long1_total: result.summary.long1_total,
          long2_total: result.summary.long2_total,
          short_total: result.summary.short_total,
          diff1: result.summary.diff1,
          diff2: result.summary.diff2,
        },
      ]
    : [];

  const resultTabs = result
    ? [
        {
          key: 'day',
          label: '每日汇总',
          children: (
            <Table
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
            <Table
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
      onCancel={() => { onClose(); setResult(null); form.resetFields(); }}
      footer={null}
      width={hasLong2 ? 1000 : 900}
      destroyOnClose
    >
      <style>{`.summary-row td { font-weight: bold !important; background: #fafafa !important; }`}</style>
      <Form form={form} layout="inline" style={{ marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <Form.Item name="coin" label="币种" rules={[{ required: true, message: '请选择' }]}>
          <Select showSearch options={coins} placeholder="搜索" style={{ width: 120 }}
            filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
        </Form.Item>
        <Form.Item name="longExchange" label="做多交易所1" rules={[{ required: true, message: '请选择' }]}>
          <Select options={exchangeOptions} style={{ width: 100 }} placeholder="选择" />
        </Form.Item>
        <Form.Item name="longExchange2" label="做多交易所2">
          <Select options={exchangeOptions} style={{ width: 100 }} placeholder="可选" allowClear />
        </Form.Item>
        <Form.Item name="shortExchange" label="做空交易所" rules={[{ required: true, message: '请选择' }]}>
          <Select options={exchangeOptions} style={{ width: 100 }} placeholder="选择" />
        </Form.Item>
        <Form.Item name="timeRange" label="时间" rules={[{ required: true, message: '请选择' }]}>
          <RangePicker showTime={{ format: 'HH:00' }} format="YYYY-MM-DD HH:00"
            presets={[
              { label: '1天', value: [dayjs().subtract(1, 'day'), dayjs()] },
              { label: '3天', value: [dayjs().subtract(3, 'day'), dayjs()] },
              { label: '7天', value: [dayjs().subtract(7, 'day'), dayjs()] },
              { label: '30天', value: [dayjs().subtract(30, 'day'), dayjs()] },
            ]} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" onClick={handleCalculate} loading={loading}>计算</Button>
        </Form.Item>
      </Form>
      {result && <Tabs items={resultTabs} />}
    </Modal>
  );
}
