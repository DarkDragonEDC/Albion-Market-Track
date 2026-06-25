import express from 'express'
import { WebSocketServer, WebSocket } from 'ws'
import { createServer } from 'http'
const app = express()
const server = createServer(app)
const wss = new WebSocketServer({ server })

// key: "itemId|location|quality|enchantment" → dados capturados
const store = new Map()

// Mapeamento de LocationId → nome legível
const LOCATION_NAMES = {
  '0006': 'Caerleon',      '6':    'Caerleon',
  '0007': 'Black Market',  '7':    'Black Market',
  '0301': 'Thetford',      '301':  'Thetford',
  '1000': 'Lymhurst',      '1002': 'Lymhurst',
  '2000': 'Bridgewatch',   '2004': 'Bridgewatch',
  '3000': 'Martlock',      '3005': 'Martlock',
  '3003': 'Black Market',
  '3008': 'Black Market',
  '4000': 'Fort Sterling', '4002': 'Fort Sterling',
  '4500': 'Brecilien',
}

app.use(express.json({ limit: '10mb' }))

app.use((req, res, next) => {
  if (req.path !== '/api/items') console.log(`→ ${req.method} ${req.path}`)
  next()
})

function processOrders(orders) {
  const now = new Date().toISOString()
  const grouped = new Map()

  for (const o of orders) {
    const key = `${o.ItemTypeId}|${o.LocationId}|${o.QualityLevel}|${o.EnchantmentLevel}`
    if (!grouped.has(key)) grouped.set(key, { sells: [], buys: [] })
    const g = grouped.get(key)
    const price = Math.round(o.UnitPriceSilver / 10000)
    if (o.AuctionType === 'offer') {
      g.sells.push({ price, amount: o.Amount })
    } else {
      g.buys.push({ price, amount: o.Amount })
    }
  }

  for (const [key, { sells, buys }] of grouped) {
    const prev = store.get(key) ?? {}
    store.set(key, {
      ...prev,
      sells: sells.sort((a, b) => a.price - b.price),
      buys: buys.sort((a, b) => b.price - a.price),
      capturedAt: now,
    })
  }

  const count = grouped.size
  console.log(`[${new Date().toLocaleTimeString('pt-BR')}] ${count} itens (${orders.length} ordens)`)
  broadcast({ type: 'update', count })
}

// Recebe ordens via HTTP (fallback se WS falhar)
app.post('/marketorders.ingest', (req, res) => {
  const orders = req.body?.Orders
  if (orders?.length) processOrders(orders)
  res.sendStatus(200)
})

app.get('/api/items', (req, res) => {
  const { location, minutes = 15 } = req.query
  const cutoff = Date.now() - parseInt(minutes) * 60_000

  const items = []
  for (const [key, data] of store) {
    if (new Date(data.capturedAt).getTime() < cutoff) continue
    const [itemId, loc, quality, enchantment] = key.split('|')
    const cityName = LOCATION_NAMES[loc] ?? loc
    if (location && location !== 'Todas' && cityName !== location && loc !== location) continue

    items.push({
      itemId,
      location: LOCATION_NAMES[loc] ?? loc,
      location_raw: loc,
      quality: parseInt(quality),
      enchantment: parseInt(enchantment),
      minSell: data.sells[0]?.price ?? null,
      maxSell: data.sells.length ? data.sells[data.sells.length - 1].price : null,
      totalSellQty: data.sells.reduce((s, o) => s + o.amount, 0),
      maxBuy: data.buys[0]?.price ?? null,
      totalBuyQty: data.buys.reduce((s, o) => s + o.amount, 0),
      capturedAt: data.capturedAt,
    })
  }

  items.sort((a, b) => new Date(b.capturedAt) - new Date(a.capturedAt))
  res.json(items)
})

app.post('/api/clear', (_req, res) => {
  store.clear()
  broadcast({ type: 'cleared' })
  res.sendStatus(200)
})

function broadcast(msg) {
  const data = JSON.stringify(msg)
  for (const client of wss.clients) {
    if (client.readyState === 1) client.send(data)
  }
}

// Conecta ao WebSocket local do Data Client (porta 8099)
function connectToDataClient() {
  const dc = new WebSocket('ws://127.0.0.1:8099/ws', {
    headers: { Origin: 'http://localhost' }
  })

  dc.on('open', () => {
    console.log('✅ Data Client WebSocket conectado (porta 8099)\n')
  })

  dc.on('message', (raw) => {
    try {
      const msg = JSON.parse(raw.toString())
      if (msg.topic === 'marketorders.ingest') {
        const orders = msg.data?.Orders ?? []
        if (orders.length) processOrders(orders)
      }
    } catch (e) {
      console.error('Erro ao parsear msg do DC:', e.message)
    }
  })

  dc.on('error', () => {})

  dc.on('close', () => {
    setTimeout(connectToDataClient, 100)
  })
}

const PORT = 3001
server.listen(PORT, () => {
  console.log(`\n🟢 Albion Scanner rodando em http://localhost:${PORT}`)
  console.log(`   Conectando ao Data Client WebSocket (porta 8099)...\n`)
  connectToDataClient()
})
