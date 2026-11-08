import { Form, Input, InputNumber, Modal } from 'antd'
import { useEffect } from 'react'
import type { ResourceCardData, ResourceInput } from '../types'

interface Props {
  open: boolean
  resource?: ResourceCardData | null
  submitting: boolean
  onCancel: () => void
  onSubmit: (value: ResourceInput) => Promise<void>
}

export function ResourceEditor({ open, resource, submitting, onCancel, onSubmit }: Props) {
  const [form] = Form.useForm<ResourceInput>()

  useEffect(() => {
    if (!open) return
    if (resource) {
      form.setFieldsValue({
        name: resource.name,
        gpu_model: resource.gpu_model,
        gpu_count: resource.gpu_count,
        cpu_cores: resource.cpu_cores,
        memory_gib: resource.memory_gib,
        default_cpu_cores: resource.default_cpu_cores,
        default_memory_gib: resource.default_memory_gib,
      })
    } else {
      form.resetFields()
    }
  }, [form, open, resource])

  return (
    <Modal
      title={resource ? '编辑算力资源' : '新建算力资源'}
      open={open}
      confirmLoading={submitting}
      onCancel={onCancel}
      onOk={() => form.validateFields().then(onSubmit)}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="name" label="资源名称" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} placeholder="例如：A100 训练集群" />
        </Form.Item>
        <Form.Item name="gpu_model" label="GPU 型号" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} placeholder="例如：NVIDIA A100 80GB" />
        </Form.Item>
        <Form.Item name="gpu_count" label="GPU 总卡数" rules={[{ required: true }]}>
          <InputNumber min={1} max={10000} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="cpu_cores" label="CPU 总核心数（逻辑核心）" rules={[{ required: true, type: 'integer', min: 1, max: 100000 }]}>
          <InputNumber min={1} max={100000} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="memory_gib" label="内存总容量（GiB）" rules={[{ required: true, type: 'integer', min: 1, max: 1048576 }]}>
          <InputNumber min={1} max={1048576} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="default_cpu_cores" label="默认申请 CPU 核心数" dependencies={['cpu_cores']} rules={[
          { required: true, type: 'integer', min: 1 },
          ({ getFieldValue }) => ({ validator: (_, value) => value <= getFieldValue('cpu_cores') ? Promise.resolve() : Promise.reject(new Error('默认值不能超过 CPU 总核心数')) }),
        ]}>
          <InputNumber min={1} precision={0} className="full-width" />
        </Form.Item>
        <Form.Item name="default_memory_gib" label="默认申请内存（GiB）" dependencies={['memory_gib']} rules={[
          { required: true, type: 'integer', min: 1 },
          ({ getFieldValue }) => ({ validator: (_, value) => value <= getFieldValue('memory_gib') ? Promise.resolve() : Promise.reject(new Error('默认值不能超过内存总容量')) }),
        ]}>
          <InputNumber min={1} precision={0} className="full-width" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

