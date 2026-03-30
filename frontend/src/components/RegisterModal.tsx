import { Modal, Form, Input, Button, message } from 'antd';
import { UserOutlined, LockOutlined, GiftOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { useAuthStore } from '../stores/authStore';
import { authApi } from '../api/auth';

export default function RegisterModal() {
  const { registerModalOpen, closeRegisterModal, openLoginModal, login } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleRegister = async (values: { username: string; password: string; confirmPassword: string; inviteCode: string }) => {
    setLoading(true);
    try {
      const res = await authApi.register(values.username, values.password, values.confirmPassword, values.inviteCode);
      login(res.access_token, res.user);
      message.success('注册成功');
      form.resetFields();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      message.error(error.response?.data?.detail || '注册失败');
    } finally {
      setLoading(false);
    }
  };

  const switchToLogin = () => {
    form.resetFields();
    openLoginModal();
  };

  return (
    <Modal
      title="注册"
      open={registerModalOpen}
      onCancel={closeRegisterModal}
      footer={null}
      destroyOnClose
    >
      <Form form={form} onFinish={handleRegister} layout="vertical">
        <Form.Item
          name="username"
          rules={[{ required: true, message: '请输入用户名' }]}
        >
          <Input prefix={<UserOutlined />} placeholder="用户名" />
        </Form.Item>
        <Form.Item
          name="password"
          rules={[
            { required: true, message: '请输入密码' },
            { min: 6, message: '密码至少6个字符' },
            {
              pattern: /^(?=.*[a-zA-Z])(?=.*\d)/,
              message: '密码必须包含字母和数字',
            },
          ]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="密码" />
        </Form.Item>
        <Form.Item
          name="confirmPassword"
          dependencies={['password']}
          rules={[
            { required: true, message: '请确认密码' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('password') === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error('两次输入的密码不一致'));
              },
            }),
          ]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="确认密码" />
        </Form.Item>
        <Form.Item
          name="inviteCode"
          rules={[{ required: true, message: '请输入邀请码' }]}
        >
          <Input prefix={<GiftOutlined />} placeholder="邀请码" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block>
            注册
          </Button>
        </Form.Item>
        <div style={{ textAlign: 'center' }}>
          已有账号？
          <Button type="link" onClick={switchToLogin}>
            立即登录
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
