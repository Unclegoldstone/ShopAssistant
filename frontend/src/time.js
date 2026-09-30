const DATABASE_DATETIME_WITHOUT_ZONE =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/

export function formatConversationTime(value) {
  const normalizedValue =
    typeof value === 'string' && DATABASE_DATETIME_WITHOUT_ZONE.test(value)
      ? `${value}Z`
      : value
  const date = new Date(normalizedValue)
  if (Number.isNaN(date.getTime())) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
