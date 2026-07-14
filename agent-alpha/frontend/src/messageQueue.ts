export interface QueuedMessage {
  id: string
  content: string
  priority?: boolean
}

export interface SessionMessageQueue {
  items: QueuedMessage[]
  paused: boolean
}

export const emptySessionMessageQueue = (): SessionMessageQueue => ({
  items: [],
  paused: false,
})

export function enqueueQueuedMessage(
  queue: SessionMessageQueue,
  message: QueuedMessage,
): SessionMessageQueue {
  return {
    ...queue,
    items: [...queue.items, { ...message, priority: false }],
  }
}

export function enqueuePriorityMessage(
  queue: SessionMessageQueue,
  message: QueuedMessage,
): SessionMessageQueue {
  let insertAt = 0
  while (insertAt < queue.items.length && queue.items[insertAt].priority) {
    insertAt += 1
  }
  return {
    paused: false,
    items: [
      ...queue.items.slice(0, insertAt),
      { ...message, priority: true },
      ...queue.items.slice(insertAt),
    ],
  }
}

export function pauseMessageQueue(queue: SessionMessageQueue): SessionMessageQueue {
  if (!queue.items.length) return queue
  return { ...queue, paused: true }
}

export function resumeMessageQueue(queue: SessionMessageQueue): SessionMessageQueue {
  if (!queue.paused) return queue
  return { ...queue, paused: false }
}

export function withdrawQueuedMessage(
  queue: SessionMessageQueue,
  messageId: string,
): SessionMessageQueue {
  const items = queue.items.filter((message) => message.id !== messageId)
  if (items.length === queue.items.length) return queue
  return {
    items,
    paused: items.length ? queue.paused : false,
  }
}

export function moveQueuedMessage(
  queue: SessionMessageQueue,
  draggedId: string,
  targetId: string,
  placement: 'before' | 'after',
): SessionMessageQueue {
  if (draggedId === targetId) return queue
  const draggedIndex = queue.items.findIndex((message) => message.id === draggedId)
  const targetIndex = queue.items.findIndex((message) => message.id === targetId)
  if (draggedIndex < 0 || targetIndex < 0) return queue

  const items = queue.items.map((message) => ({ ...message, priority: false }))
  const [dragged] = items.splice(draggedIndex, 1)
  const adjustedTargetIndex = items.findIndex((message) => message.id === targetId)
  const insertAt = placement === 'after' ? adjustedTargetIndex + 1 : adjustedTargetIndex
  items.splice(insertAt, 0, dragged)
  return { ...queue, items }
}

export function takeNextQueuedMessage(queue: SessionMessageQueue): {
  message: QueuedMessage | null
  queue: SessionMessageQueue
} {
  if (queue.paused || !queue.items.length) {
    return { message: null, queue }
  }
  const [message, ...items] = queue.items
  return {
    message,
    queue: {
      items,
      paused: false,
    },
  }
}
