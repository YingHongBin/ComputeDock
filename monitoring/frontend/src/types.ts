export interface AdminSession {
  username: string
  csrf_token: string
}

export interface ResourceCardData {
  id: string
  name: string
  gpu_model: string
  gpu_count: number
  allocated_gpu_count: number
  available_gpu_count: number
  overallocated: boolean
  token: string
  created_at?: string
}

export interface ResourceInput {
  name: string
  gpu_model: string
  gpu_count: number
}

export interface ContainerSummary {
  id: string
  name: string
  generation: number
  status: 'online' | 'offline'
  last_received_at: string
  allocated_gpu_count: number
  utilization_1h: number | null
  utilization_6h: number | null
  utilization_1d: number | null
  utilization_7d: number | null
}

export interface ChartPoint {
  time: string
  memory_used: number | null
  memory_total: number | null
  utilization: number | null
}

export interface GpuChartSeries {
  gpuid: string
  shared: boolean
  first_reported_at: string
  last_reported_at: string
  points: ChartPoint[]
}

export interface ChartResponse {
  container_id: string
  container_name: string
  range: ChartRange
  bucket_seconds: number
  window_start: string
  window_end: string
  instance_first_reported_at: string
  instance_removed_at: string | null
  series: GpuChartSeries[]
}

export type ChartRange = '1h' | '6h' | '1d' | '7d'
