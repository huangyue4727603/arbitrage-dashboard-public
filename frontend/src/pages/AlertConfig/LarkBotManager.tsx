import { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Input, Space, Popconfirm, message, Tooltip } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getLarkBots,
  createLarkBot,
  updateLarkBot,
  deleteLarkBot,
} from '../../api/alert';
import type { LarkBot, LarkBotForm } from '../../api/alert';

interface LarkBotManagerProps {
  onSelect?: (bot: LarkBot) => void;
}

export default function LarkBotManager({ onSelect }: LarkBotManagerProps) {
  const [bots, setBots] = useState<LarkBot[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingBot, setEditingBot] = useState<LarkBot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<LarkBotForm>();

  const fetchBots = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getLarkBots();
      setBots(data);
    } catch {
      message.error('获取机器人列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBots();
  }, [fetchBots]);

  const openAddModal = () => {
    setEditingBot(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEditModal = (bot: LarkBot) => {
    setEditingBot(bot);
    form.setFieldsValue({ name: bot.name, webhook_url: bot.webhook_url });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      if (editingBot) {
        await updateLarkBot(editingBot.id, values);
        message.success('更新成功');
      } else {
        await createLarkBot(values);
        message.success('添加成功');
      }
      setModalOpen(false);
      form.resetFields();
      setEditingBot(null);
      fetchBots();
    } catch {
      // validation or api error
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteLarkBot(id);
      message.success('删除成功');
      fetchBots();
    } catch {
      message.error('删除失败');
    }
  };

  const columns: ColumnsType<LarkBot> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: 'Webhook URL',
      dataIndex: 'webhook_url',
      key: 'webhook_url',
      ellipsis: true,
      render: (url: string) => (
        <Tooltip title={url}>
          {url.length > 50 ? `${url.slice(0, 50)}...` : url}
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_, record) => (
        <Space>
          {onSelect && (
            <Button type="link" size="small" onClick={() => onSelect(record)}>
              选择
            </Button>
          )}
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEditModal(record)}
          />
          <Popconfirm
            title="确定删除此机器人？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 600, fontSize: 15 }}>飞书机器人管理</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openAddModal}>
          添加机器人
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={bots}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={false}
      />
      <Modal
        title={editingBot ? '编辑机器人' : '添加机器人'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
          setEditingBot(null);
        }}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText="确定"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入机器人名称' }]}
          >
            <Input placeholder="如：预警通知群" />
          </Form.Item>
          <Form.Item
            name="webhook_url"
            label="Webhook URL"
            rules={[
              { required: true, message: '请输入 Webhook URL' },
              { type: 'url', message: '请输入有效的 URL' },
            ]}
          >
            <Input placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export { type LarkBotManagerProps };
