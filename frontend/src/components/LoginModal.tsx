import { Modal, Form, Input, Button, message } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { useAuthStore } from '../stores/authStore';
import { authApi } from '../api/auth';

export default function LoginModal() {
  const { loginModalOpen, closeLoginModal, openRegisterModal, login } = useAuthStore();
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const res = await authApi.login(values.username, values.password);
      login(res.access_token, res.user);
      message.success('登录成功');
      form.resetFields();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      message.error(error.response?.data?.detail || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const switchToRegister = () => {
    form.resetFields();
    openRegisterModal();
  };

  return (
    <Modal
      title="登录"
      open={loginModalOpen}
      onCancel={closeLoginModal}
      footer={null}
      destroyOnClose
    >
      <Form form={form} onFinish={handleLogin} layout="vertical">
        <Form.Item
          name="username"
          rules={[{ required: true, message: '请输入用户名' }]}
        >
          <Input prefix={<UserOutlined />} placeholder="用户名" />
        </Form.Item>
        <Form.Item
          name="password"
          rules={[{ required: true, message: '请输入密码' }]}
        >
          <Input.Password prefix={<LockOutlined />} placeholder="密码" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} block>
            登录
          </Button>
        </Form.Item>
        <div style={{ textAlign: 'center' }}>
          还没有账号？
          <Button type="link" onClick={switchToRegister}>
            立即注册
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
