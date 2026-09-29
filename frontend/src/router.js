import { createRouter, createWebHashHistory } from 'vue-router'

import ChatView from './views/ChatView.vue'
import TestLabView from './views/TestLabView.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/tests', name: 'tests', component: TestLabView },
  ],
})
