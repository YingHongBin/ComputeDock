import { Alert, App, Button, Form, Input, Modal } from 'antd'
import { useState } from 'react'
import { api, csrfHeaders, errorMessage } from '../api'
import { useAuth } from '../auth'

export function EmailVerificationPrompt() {
  const { session } = useAuth()
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form] = Form.useForm()

  const verify = async ({ current_password }: { current_password: string }) => {
    if (!session) return
    setBusy(true)
    try {
      await api.post('/auth/email/change-request', {
        new_email: session.email,
        current_password,
      }, { headers: csrfHeaders(session.csrf_token) })
      message.success('验证邮件已提交发送，请查收邮箱。')
      setOpen(false)
      form.resetFields()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  if (!session || session.email_verified) return null

  return (
    <>
      <Alert
        type="info"
        showIcon
        message="邮箱尚未验证，验证后可通过邮箱找回密码。"
        action={<Button size="small" onClick={() => setOpen(true)}>验证邮箱</Button>}
        style={{ marginBottom: 16 }}
      />
      <Modal title="验证邮箱" open={open} onCancel={() => { setOpen(false); form.resetFields() }} onOk={() => form.submit()} okText="发送验证邮件" confirmLoading={busy} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={verify} preserve={false}>
          <Form.Item label="邮箱"><Input value={session.email} readOnly /></Form.Item>
          <Form.Item name="current_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
