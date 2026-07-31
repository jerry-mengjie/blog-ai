// 可注入的 router 代理: 由入口挂载真实实例, api 层只依赖本模块
// 避免「页面 → api → router → 懒加载页面」的静态循环引用导致 hash 级联失效
let routerInstance = null

// 入口注入真实 router
export const setRouter = (router) => {
  routerInstance = router
}

// 代理对象, 调用处仍可写 router.push('/personal')
export const router = {
  push: (...args) => routerInstance?.push(...args)
}
