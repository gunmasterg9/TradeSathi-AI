import { useEffect, useState, useRef, useMemo } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  ArrowRightLeft,
  Barcode,
  Boxes,
  Camera,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Copy,
  Eye,
  FileCheck2,
  FileText,
  Filter,
  History,
  Info,
  Layers,
  MapPin,
  Package,
  Printer,
  QrCode,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  ShoppingCart,
  Trash2,
  Truck,
  Warehouse,
  X,
  XCircle,
} from 'lucide-react'
import { Html5Qrcode } from 'html5-qrcode'
import { apiFetch, API_BASE } from './api'

// Audio feedback for barcode gun / camera recognition
function playBeep(success = true) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = success ? 'sine' : 'sawtooth'
    osc.frequency.setValueAtTime(success ? 900 : 250, ctx.currentTime)
    gain.gain.setValueAtTime(0.12, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + (success ? 0.12 : 0.25))
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + (success ? 0.12 : 0.25))
  } catch {
    // AudioContext not available in current environment; ignore
  }
}

export default function PortalView({ initialTab = 'lookup' }) {
  const [activeTab, setActiveTab] = useState(initialTab) // 'lookup' | 'receipt' | 'transfer' | 'packing' | 'cargo' | 'labels'
  const [currentRole, setCurrentRole] = useState('warehouse') // 'warehouse' | 'admin' | 'procurement' | 'sales' | 'viewer'
  const [operatorName, setOperatorName] = useState('Warehouse Operator 1')

  const authHeaders = useMemo(
    () => ({
      'X-User-Role': currentRole,
      'X-User-Name': operatorName,
    }),
    [currentRole, operatorName]
  )

  // Scanner Input State (Hardware gun & manual)
  const [scannedInput, setScannedInput] = useState('')
  const [isScanningActive, setIsScanningActive] = useState(false)
  const [scanHistory, setScanHistory] = useState([])
  const [showScanHistory, setShowScanHistory] = useState(false)
  const [portalError, setPortalError] = useState(null)
  const [portalSuccess, setPortalSuccess] = useState(null)
  const [loading, setLoading] = useState(false)

  // Camera Scanner Modal State
  const [isCameraOpen, setIsCameraOpen] = useState(false)
  const [cameraError, setCameraError] = useState(null)
  const [camerasList, setCamerasList] = useState([])
  const [selectedCameraId, setSelectedCameraId] = useState('')
  const html5QrCodeRef = useRef(null)
  const barcodeInputRef = useRef(null)

  // Active Resolved Entity
  const [resolvedEntity, setResolvedEntity] = useState(null)

  // Confirmation Dialog State (Safety Rule: Scanning never mutates stock automatically)
  const [confirmModal, setConfirmModal] = useState({
    isOpen: false,
    title: '',
    message: '',
    actionType: null, // 'receipt' | 'transfer' | 'pack'
    payload: null,
  })

  // Workflow State: Inbound Receipt
  const [receiptState, setReceiptState] = useState({
    poData: null,
    targetWarehouseId: '',
    targetLocationId: '',
    lineItems: [], // { product_id, sku, product_name, ordered_qty, received_qty, accepted_qty, rejected_qty, quarantined_qty }
  })

  // Workflow State: Warehouse Transfer
  const [transferState, setTransferState] = useState({
    sourceLocationId: '',
    sourceLocationCode: '',
    targetLocationId: '',
    targetLocationCode: '',
    sourceWarehouseId: '',
    targetWarehouseId: '',
    productId: '',
    productSku: '',
    productName: '',
    atpAvailable: 0,
    transferQty: 1,
    notes: '',
  })

  // Workflow State: Sales Order Packing
  const [packingState, setPackingState] = useState({
    soData: null,
    lines: [], // { line_id, product_id, sku, product_name, ordered_qty, allocated_qty, picked_qty, pack_input }
    targetPackageNumber: '',
  })

  // Label Station State
  const [labelForm, setLabelForm] = useState({
    entity_type: 'PRODUCT',
    entity_id: '',
    label_size: '4x2', // '4x2' | '2x1'
    symbology: 'BOTH', // 'QR_CODE' | 'CODE128' | 'BOTH'
  })
  const [labelPreviewHtml, setLabelPreviewHtml] = useState('')
  const [recentLabels, setRecentLabels] = useState([])
  const [labelLoading, setLabelLoading] = useState(false)

  // Master Data caches for selectors
  const [masterProducts, setMasterProducts] = useState([])
  const [masterWarehouses, setMasterWarehouses] = useState([])
  const [masterLocations, setMasterLocations] = useState([])

  // Load Initial Master Data & Recent Labels
  useEffect(() => {
    fetchMasterData()
    fetchRecentLabels()
  }, [])

  // Auto-focus barcode input
  useEffect(() => {
    if (barcodeInputRef.current) {
      barcodeInputRef.current.focus()
    }
  }, [activeTab])

  const fetchMasterData = async () => {
    try {
      const [prodRes, whRes, locRes] = await Promise.all([
        apiFetch('/api/master-data/products', { headers: authHeaders }).catch(() => []),
        apiFetch('/api/warehouses', { headers: authHeaders }).catch(() => []),
        apiFetch('/api/warehouses/locations', { headers: authHeaders }).catch(() => []),
      ])
      setMasterProducts(Array.isArray(prodRes) ? prodRes : prodRes?.items || [])
      setMasterWarehouses(Array.isArray(whRes) ? whRes : whRes?.items || [])
      setMasterLocations(Array.isArray(locRes) ? locRes : locRes?.items || [])
    } catch {
      // Non-critical background fetch failure
    }
  }

  const fetchRecentLabels = async () => {
    try {
      const res = await apiFetch('/api/portal/labels', { headers: authHeaders })
      setRecentLabels(res?.items || [])
    } catch {
      // Non-critical
    }
  }

  // Camera Management
  const startCamera = async () => {
    setIsCameraOpen(true)
    setCameraError(null)

    try {
      const devices = await Html5Qrcode.getCameras()
      if (devices && devices.length) {
        setCamerasList(devices)
        const backCam = devices.find((d) => d.label.toLowerCase().includes('back') || d.label.toLowerCase().includes('environment'))
        const camId = backCam ? backCam.id : devices[0].id
        setSelectedCameraId(camId)
        initHtml5Scanner(camId)
      } else {
        setCameraError('No cameras detected on this device.')
      }
    } catch (err) {
      setCameraError(
        'Camera permission was denied or is unavailable in an insecure HTTP context. Please check browser permissions or use a handheld barcode scanner.'
      )
    }
  }

  const initHtml5Scanner = (cameraId) => {
    if (html5QrCodeRef.current) {
      try {
        html5QrCodeRef.current.stop().catch(() => {})
      } catch {}
    }

    // Wait for DOM element
    setTimeout(() => {
      const element = document.getElementById('portal-qr-reader')
      if (!element) return

      const html5QrCode = new Html5Qrcode('portal-qr-reader')
      html5QrCodeRef.current = html5QrCode

      html5QrCode
        .start(
          cameraId,
          {
            fps: 12,
            qrbox: { width: 260, height: 260 },
            aspectRatio: 1.0,
          },
          (decodedText) => {
            playBeep(true)
            handleIncomingScan(decodedText)
            closeCamera()
          },
          () => {
            // Frame decode error; ignore continuous non-matches
          }
        )
        .catch((err) => {
          setCameraError(`Camera init error: ${err?.message || err}`)
        })
    }, 150)
  }

  const closeCamera = () => {
    if (html5QrCodeRef.current) {
      try {
        html5QrCodeRef.current
          .stop()
          .then(() => {
            html5QrCodeRef.current.clear()
            html5QrCodeRef.current = null
          })
          .catch(() => {
            html5QrCodeRef.current = null
          })
      } catch {
        html5QrCodeRef.current = null
      }
    }
    setIsCameraOpen(false)
  }

  // Handle incoming scan string (from Camera or Keyboard Wedge)
  const handleIncomingScan = async (rawCode) => {
    const code = (rawCode || '').trim()
    if (!code) return

    setPortalError(null)
    setPortalSuccess(null)
    setLoading(true)

    // Add to scan history
    setScanHistory((prev) => [
      { code, timestamp: new Date().toLocaleTimeString(), id: Date.now() },
      ...prev.slice(0, 19),
    ])

    try {
      const res = await apiFetch('/api/portal/scan-resolve', {
        method: 'POST',
        headers: {
          ...authHeaders,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ barcode_value: code }),
      })

      playBeep(true)
      setResolvedEntity(res)
      routeScanByContext(res, code)
    } catch (err) {
      playBeep(false)
      setPortalError(err.message || 'Scan resolution failed')
      setResolvedEntity(null)
    } finally {
      setLoading(false)
      setScannedInput('')
      if (barcodeInputRef.current) {
        barcodeInputRef.current.focus()
      }
    }
  }

  // Route scanned payload intelligently based on entity type or active tab
  const routeScanByContext = (res, rawCode) => {
    const { entity_type, entity } = res

    // Tab 1: Universal Lookup shows whatever was resolved
    if (activeTab === 'lookup') {
      return
    }

    // Tab 2: Inbound Goods Receipt
    if (activeTab === 'receipt') {
      if (entity_type === 'PURCHASE_ORDER') {
        const lines = (entity.line_items || []).map((li) => ({
          product_id: li.product_id,
          sku: li.sku || `SKU-${li.product_id}`,
          product_name: li.product_name || `Product #${li.product_id}`,
          ordered_qty: li.ordered_qty || 0,
          received_qty: li.received_qty || 0,
          accepted_qty: Math.max(0, (li.ordered_qty || 0) - (li.received_qty || 0)),
          rejected_qty: 0,
          quarantined_qty: 0,
        }))
        setReceiptState((prev) => ({
          ...prev,
          poData: entity,
          lineItems: lines,
        }))
        setPortalSuccess(`Loaded Purchase Order ${entity.po_number || entity.id}`)
      } else if (entity_type === 'PRODUCT') {
        // Quick adjust line for scanned SKU
        setReceiptState((prev) => {
          const matchIndex = prev.lineItems.findIndex((li) => li.product_id === entity.id || li.sku === entity.sku)
          if (matchIndex >= 0) {
            const nextLines = [...prev.lineItems]
            nextLines[matchIndex].accepted_qty += 1
            return { ...prev, lineItems: nextLines }
          }
          return prev
        })
      } else if (entity_type === 'LOCATION') {
        setReceiptState((prev) => ({
          ...prev,
          targetLocationId: entity.id,
          targetWarehouseId: entity.warehouse_id || prev.targetWarehouseId,
        }))
        setPortalSuccess(`Set destination location to ${entity.location_code}`)
      }
    }

    // Tab 3: Warehouse Transfer
    if (activeTab === 'transfer') {
      if (entity_type === 'LOCATION') {
        if (!transferState.sourceLocationId) {
          setTransferState((prev) => ({
            ...prev,
            sourceLocationId: entity.id,
            sourceLocationCode: entity.location_code,
            sourceWarehouseId: entity.warehouse_id,
          }))
          setPortalSuccess(`Step 1 Complete: Source location set to ${entity.location_code}`)
        } else if (!transferState.targetLocationId) {
          setTransferState((prev) => ({
            ...prev,
            targetLocationId: entity.id,
            targetLocationCode: entity.location_code,
            targetWarehouseId: entity.warehouse_id,
          }))
          setPortalSuccess(`Step 3 Complete: Destination location set to ${entity.location_code}`)
        }
      } else if (entity_type === 'PRODUCT') {
        const atp = entity.stock_balances?.available ?? 0
        setTransferState((prev) => ({
          ...prev,
          productId: entity.id,
          productSku: entity.sku,
          productName: entity.name,
          atpAvailable: atp,
        }))
        setPortalSuccess(`Step 2 Complete: Selected product ${entity.sku} (Available ATP: ${atp})`)
      }
    }

    // Tab 4: Sales Order Packing
    if (activeTab === 'packing') {
      if (entity_type === 'SALES_ORDER') {
        const lines = (entity.line_items || []).map((li) => ({
          line_id: li.id,
          product_id: li.product_id,
          sku: li.sku || `SKU-${li.product_id}`,
          product_name: li.product_name || `Product #${li.product_id}`,
          ordered_qty: li.ordered_quantity || 0,
          allocated_qty: li.allocated_quantity || 0,
          picked_qty: li.picked_quantity || 0,
          pack_input: 1,
        }))
        setPackingState({
          soData: entity,
          lines,
          targetPackageNumber: `PKG-${entity.order_number || entity.id}-01`,
        })
        setPortalSuccess(`Loaded Sales Order ${entity.order_number || entity.id}`)
      } else if (entity_type === 'PRODUCT') {
        // Increment packed count for scanned SKU
        setPackingState((prev) => {
          const idx = prev.lines.findIndex((li) => li.product_id === entity.id || li.sku === entity.sku)
          if (idx >= 0) {
            const nextLines = [...prev.lines]
            const line = nextLines[idx]
            if (line.picked_qty + line.pack_input < line.allocated_qty) {
              line.pack_input += 1
            }
            return { ...prev, lines: nextLines }
          }
          return prev
        })
      }
    }

    // Tab 5: Cargo
    if (activeTab === 'cargo') {
      // Cargo automatically displays resolved shipment/package
    }
  }

  // Keyboard wedge listener (Enter triggers scan)
  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleIncomingScan(scannedInput)
    }
  }

  // Explicit Action Confirmation Handlers
  const openConfirmReceiptModal = () => {
    if (!receiptState.poData) {
      setPortalError('Please scan or select a Purchase Order first.')
      return
    }
    const totalQty = receiptState.lineItems.reduce(
      (sum, li) => sum + Number(li.accepted_qty || 0) + Number(li.rejected_qty || 0) + Number(li.quarantined_qty || 0),
      0
    )
    if (totalQty <= 0) {
      setPortalError('Received quantity must be greater than zero.')
      return
    }

    setConfirmModal({
      isOpen: true,
      title: 'Confirm Inbound Goods Receipt',
      message: `You are about to post a Goods Receipt for PO #${receiptState.poData.po_number || receiptState.poData.id} with ${totalQty} units across ${receiptState.lineItems.length} lines. This operation will commit inventory ledger records and update on-hand balances.`,
      actionType: 'receipt',
      payload: {
        po_id: receiptState.poData.id,
        warehouse_id: receiptState.targetWarehouseId || (masterWarehouses[0]?.id ?? 1),
        items: receiptState.lineItems
          .filter((li) => Number(li.accepted_qty || 0) + Number(li.rejected_qty || 0) + Number(li.quarantined_qty || 0) > 0)
          .map((li) => ({
            product_id: li.product_id,
            ordered_qty: li.ordered_qty,
            received_qty: Number(li.accepted_qty || 0) + Number(li.rejected_qty || 0) + Number(li.quarantined_qty || 0),
            accepted_qty: Number(li.accepted_qty || 0),
            rejected_qty: Number(li.rejected_qty || 0),
            quarantined_qty: Number(li.quarantined_qty || 0),
          })),
        notes: `Scan receipt via Operational Portal by ${operatorName}`,
      },
    })
  }

  const openConfirmTransferModal = () => {
    if (!transferState.sourceLocationId || !transferState.targetLocationId) {
      setPortalError('Please scan both source and target locations.')
      return
    }
    if (!transferState.productId) {
      setPortalError('Please scan or select a product to transfer.')
      return
    }
    const qty = Number(transferState.transferQty) || 0
    if (qty <= 0) {
      setPortalError('Transfer quantity must be greater than zero.')
      return
    }

    setConfirmModal({
      isOpen: true,
      title: 'Confirm Location Transfer',
      message: `Transfer ${qty} units of ${transferState.productSku} (${transferState.productName}) from ${transferState.sourceLocationCode || 'Source'} to ${transferState.targetLocationCode || 'Target'}? This will immediately move stock balances between bins.`,
      actionType: 'transfer',
      payload: {
        source_location_id: transferState.sourceLocationId,
        dest_location_id: transferState.targetLocationId,
        product_id: transferState.productId,
        quantity: qty,
        notes: transferState.notes || `Scanned transfer by ${operatorName}`,
      },
    })
  }

  const openConfirmPackModal = () => {
    if (!packingState.soData) {
      setPortalError('Please scan a Sales Order first.')
      return
    }
    const activeLines = packingState.lines.filter((li) => Number(li.pack_input || 0) > 0)
    if (!activeLines.length) {
      setPortalError('No items selected for packing.')
      return
    }

    setConfirmModal({
      isOpen: true,
      title: 'Confirm Sales Fulfilment Packing',
      message: `Confirm packing verification for Sales Order #${packingState.soData.order_number || packingState.soData.id}? Verified items will be recorded into package ${packingState.targetPackageNumber || 'DEFAULT'}.`,
      actionType: 'pack',
      payload: {
        sales_order_id: packingState.soData.id,
        items: activeLines.map((li) => ({
          sales_order_line_id: li.line_id,
          product_id: li.product_id,
          packed_quantity: Number(li.pack_input),
        })),
        package_number: packingState.targetPackageNumber || `PKG-${packingState.soData.id}-01`,
        notes: `Scan packing verification by ${operatorName}`,
      },
    })
  }

  const executeConfirmedAction = async () => {
    const { actionType, payload } = confirmModal
    setLoading(true)
    setPortalError(null)

    try {
      if (actionType === 'receipt') {
        const res = await apiFetch('/api/portal/execute-receipt', {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        setPortalSuccess(`Inbound Receipt Posted: GR #${res.receipt_number || res.id} created successfully!`)
        setReceiptState({
          poData: null,
          targetWarehouseId: '',
          targetLocationId: '',
          lineItems: [],
        })
      } else if (actionType === 'transfer') {
        const res = await apiFetch('/api/portal/execute-transfer', {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        setPortalSuccess(`Stock Transfer Confirmed: Movement recorded successfully!`)
        setTransferState({
          sourceLocationId: '',
          sourceLocationCode: '',
          targetLocationId: '',
          targetLocationCode: '',
          sourceWarehouseId: '',
          targetWarehouseId: '',
          productId: '',
          productSku: '',
          productName: '',
          atpAvailable: 0,
          transferQty: 1,
          notes: '',
        })
      } else if (actionType === 'pack') {
        const res = await apiFetch('/api/portal/execute-pack', {
          method: 'POST',
          headers: { ...authHeaders, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        setPortalSuccess(`Packing Verified: SO #${payload.sales_order_id} progress updated!`)
        // Refresh SO data
        if (packingState.soData) {
          handleIncomingScan(`TS:v1:SO:${packingState.soData.id}`)
        }
      }
      setConfirmModal({ isOpen: false, title: '', message: '', actionType: null, payload: null })
      playBeep(true)
    } catch (err) {
      playBeep(false)
      setPortalError(err.message || 'Operation failed')
      setConfirmModal({ isOpen: false, title: '', message: '', actionType: null, payload: null })
    } finally {
      setLoading(false)
    }
  }

  // Label Generation & Printing Handlers
  const handleGenerateLabel = async () => {
    if (!labelForm.entity_id) {
      setPortalError('Please select or specify an entity ID for the label.')
      return
    }
    setLabelLoading(true)
    setPortalError(null)

    try {
      const res = await apiFetch('/api/portal/labels/generate', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_type: labelForm.entity_type,
          entity_id: Number(labelForm.entity_id) || labelForm.entity_id,
          label_size: labelForm.label_size,
          symbology: labelForm.symbology,
        }),
      })

      setPortalSuccess(`Label generated: ${res.barcode_value}`)
      fetchRecentLabels()
      handlePreviewLabel(res.id)
    } catch (err) {
      setPortalError(err.message || 'Label generation failed')
    } finally {
      setLabelLoading(false)
    }
  }

  const handlePreviewLabel = async (labelId) => {
    setLabelLoading(true)
    try {
      const html = await apiFetch(`/api/portal/labels/${labelId}/preview`, {
        headers: authHeaders,
      })
      setLabelPreviewHtml(html)
    } catch (err) {
      setPortalError(err.message || 'Could not load label preview')
    } finally {
      setLabelLoading(false)
    }
  }

  const handleDeactivateLabel = async (labelId) => {
    if (!window.confirm('Are you sure you want to deactivate this barcode? Once deactivated, it cannot be scanned.')) {
      return
    }
    setLabelLoading(true)
    try {
      await apiFetch(`/api/portal/labels/${labelId}/deactivate`, {
        method: 'POST',
        headers: authHeaders,
      })
      setPortalSuccess(`Label #${labelId} deactivated successfully.`)
      fetchRecentLabels()
      if (labelPreviewHtml) {
        setLabelPreviewHtml('')
      }
    } catch (err) {
      setPortalError(err.message || 'Deactivation failed')
    } finally {
      setLabelLoading(false)
    }
  }

  const handlePrintIframe = () => {
    const iframe = document.getElementById('label-print-iframe')
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.focus()
      iframe.contentWindow.print()
    }
  }

  // Quick Sample Injector for Instant Testing
  const handleLoadSample = (sampleType) => {
    if (sampleType === 'PRODUCT') {
      const p = masterProducts[0]
      if (p) handleIncomingScan(`TS:v1:PRODUCT:${p.id}`)
      else handleIncomingScan('TS:v1:PRODUCT:1')
    } else if (sampleType === 'LOCATION') {
      const l = masterLocations[0]
      if (l) handleIncomingScan(`TS:v1:LOCATION:${l.id}`)
      else handleIncomingScan('TS:v1:LOCATION:1')
    } else if (sampleType === 'PO') {
      handleIncomingScan('TS:v1:PO:1')
    } else if (sampleType === 'SO') {
      handleIncomingScan('TS:v1:SO:1')
    } else if (sampleType === 'SHIPMENT') {
      handleIncomingScan('TS:v1:SHIPMENT:1')
    }
  }

  return (
    <div className="portal-container">
      {/* Header Bar: Operational Portals & Role Selection */}
      <div className="portal-header-bar">
        <div className="portal-header-left">
          <div className="portal-logo-badge">
            <Barcode size={24} />
          </div>
          <div>
            <h1 className="portal-title">Operational Barcode &amp; QR Portal</h1>
            <p className="portal-subtitle">
              High-throughput warehouse scanning, inventory tracking &amp; thermal label station
            </p>
          </div>
        </div>

        {/* Role & Operator Bar */}
        <div className="portal-role-bar">
          <div className="portal-role-item">
            <Shield size={14} />
            <label>Role:</label>
            <select
              value={currentRole}
              onChange={(e) => setCurrentRole(e.target.value)}
              className="portal-role-select"
            >
              <option value="warehouse">Warehouse Operator</option>
              <option value="admin">Administrator</option>
              <option value="procurement">Procurement</option>
              <option value="sales">Sales &amp; Fulfilment</option>
              <option value="viewer">Viewer (Read-only)</option>
            </select>
          </div>
          <div className="portal-role-item">
            <label>Operator:</label>
            <input
              type="text"
              value={operatorName}
              onChange={(e) => setOperatorName(e.target.value)}
              className="portal-operator-input"
            />
          </div>
        </div>
      </div>

      {/* Global Status Banners */}
      {portalError && (
        <div className="portal-alert portal-alert-error">
          <AlertTriangle size={18} />
          <div className="portal-alert-text">{portalError}</div>
          <button className="portal-alert-close" onClick={() => setPortalError(null)}>
            <X size={16} />
          </button>
        </div>
      )}

      {portalSuccess && (
        <div className="portal-alert portal-alert-success">
          <CheckCircle2 size={18} />
          <div className="portal-alert-text">{portalSuccess}</div>
          <button className="portal-alert-close" onClick={() => setPortalSuccess(null)}>
            <X size={16} />
          </button>
        </div>
      )}

      {/* Primary Scanner Gun / Manual Barcode Input Section */}
      <div className="portal-scan-card">
        <div className="portal-scan-input-wrapper">
          <div className="portal-scan-icon">
            <QrCode size={22} />
          </div>
          <input
            ref={barcodeInputRef}
            type="text"
            className="portal-scan-input"
            placeholder="Scan barcode / QR with handheld scanner gun, or type and press Enter..."
            value={scannedInput}
            onChange={(e) => setScannedInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          {scannedInput && (
            <button
              className="portal-input-clear-btn"
              onClick={() => setScannedInput('')}
              title="Clear input"
            >
              <X size={16} />
            </button>
          )}
          <button
            className="portal-action-btn portal-submit-scan-btn"
            onClick={() => handleIncomingScan(scannedInput)}
            disabled={loading || !scannedInput.trim()}
          >
            {loading ? <RefreshCw className="spin" size={16} /> : <ArrowRight size={16} />}
            <span>Lookup</span>
          </button>
          <button
            className="portal-action-btn portal-camera-trigger-btn"
            onClick={startCamera}
            disabled={loading}
            title="Open camera-based barcode/QR scanner"
          >
            <Camera size={18} />
            <span>Camera</span>
          </button>
        </div>

        {/* Quick sample buttons & scan history toggle */}
        <div className="portal-scan-helpers">
          <div className="portal-quick-samples">
            <span className="helper-label">Quick Test Codes:</span>
            <button onClick={() => handleLoadSample('PRODUCT')} className="sample-pill">
              Sample SKU
            </button>
            <button onClick={() => handleLoadSample('LOCATION')} className="sample-pill">
              Sample Bin
            </button>
            <button onClick={() => handleLoadSample('PO')} className="sample-pill">
              Sample PO
            </button>
            <button onClick={() => handleLoadSample('SO')} className="sample-pill">
              Sample SO
            </button>
            <button onClick={() => handleLoadSample('SHIPMENT')} className="sample-pill">
              Sample Cargo
            </button>
          </div>

          <button
            className="portal-history-toggle"
            onClick={() => setShowScanHistory(!showScanHistory)}
          >
            <History size={14} />
            <span>Scan History ({scanHistory.length})</span>
          </button>
        </div>

        {/* Scan History Drawer */}
        {showScanHistory && (
          <div className="portal-history-drawer">
            <div className="history-drawer-header">
              <span>Recent Scans</span>
              <button onClick={() => setScanHistory([])} className="history-clear-btn">
                Clear
              </button>
            </div>
            {scanHistory.length === 0 ? (
              <div className="history-empty">No scans recorded yet in this session.</div>
            ) : (
              <div className="history-list">
                {scanHistory.map((item) => (
                  <div
                    key={item.id}
                    className="history-item"
                    onClick={() => handleIncomingScan(item.code)}
                  >
                    <Barcode size={14} />
                    <span className="history-code">{item.code}</span>
                    <span className="history-time">{item.timestamp}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Operational Portal Navigation Tabs */}
      <div className="portal-tabs-nav">
        <button
          className={`portal-tab-btn ${activeTab === 'lookup' ? 'active' : ''}`}
          onClick={() => setActiveTab('lookup')}
        >
          <Search size={16} />
          <span>Universal Lookup</span>
        </button>
        <button
          className={`portal-tab-btn ${activeTab === 'receipt' ? 'active' : ''}`}
          onClick={() => setActiveTab('receipt')}
        >
          <Boxes size={16} />
          <span>Inbound Goods Receipt</span>
        </button>
        <button
          className={`portal-tab-btn ${activeTab === 'transfer' ? 'active' : ''}`}
          onClick={() => setActiveTab('transfer')}
        >
          <ArrowRightLeft size={16} />
          <span>Location Transfer</span>
        </button>
        <button
          className={`portal-tab-btn ${activeTab === 'packing' ? 'active' : ''}`}
          onClick={() => setActiveTab('packing')}
        >
          <Package size={16} />
          <span>Sales Pick &amp; Pack</span>
        </button>
        <button
          className={`portal-tab-btn ${activeTab === 'cargo' ? 'active' : ''}`}
          onClick={() => setActiveTab('cargo')}
        >
          <Truck size={16} />
          <span>Export Cargo &amp; Customs</span>
        </button>
        <button
          className={`portal-tab-btn ${activeTab === 'labels' ? 'active' : ''}`}
          onClick={() => setActiveTab('labels')}
        >
          <Printer size={16} />
          <span>Label Station</span>
        </button>
      </div>

      {/* TAB CONTENT AREAS */}

      {/* TAB 1: Universal Entity Lookup */}
      {activeTab === 'lookup' && (
        <div className="portal-view-section">
          {!resolvedEntity ? (
            <div className="portal-empty-state">
              <QrCode size={48} className="empty-icon" />
              <h3>Scan Any Entity Barcode or QR Code</h3>
              <p>
                Supports Products/SKUs, Warehouse Locations/Bins, Purchase Orders, Goods Receipts,
                Sales Orders, Packages, and Export Shipments.
              </p>
            </div>
          ) : (
            <div className="entity-result-card">
              <div className="entity-card-header">
                <div className="entity-badge-group">
                  <span className="entity-type-badge">{resolvedEntity.entity_type}</span>
                  <span className="entity-barcode-badge">{resolvedEntity.barcode_value}</span>
                </div>
                <div className="entity-meta-actions">
                  <span className="statutory-tag">OPERATIONAL LOOKUP ONLY</span>
                </div>
              </div>

              {/* Entity: PRODUCT */}
              {resolvedEntity.entity_type === 'PRODUCT' && (
                <div className="entity-detail-body">
                  <div className="entity-title-row">
                    <div>
                      <h2>{resolvedEntity.entity.name}</h2>
                      <div className="entity-sub-meta">
                        <span>SKU: <strong>{resolvedEntity.entity.sku}</strong></span>
                        <span>HS Code: <strong>{resolvedEntity.entity.hs_code || 'N/A'}</strong></span>
                        <span>Category: <strong>{resolvedEntity.entity.category || 'General'}</strong></span>
                      </div>
                    </div>
                    <div className="stock-health-badge">
                      {(resolvedEntity.entity.stock_balances?.available ?? 0) <= (resolvedEntity.entity.reorder_point ?? 0) ? (
                        <span className="health-tag tag-low">LOW STOCK</span>
                      ) : (
                        <span className="health-tag tag-ok">STOCK HEALTHY</span>
                      )}
                    </div>
                  </div>

                  {/* Stock Breakdown Grid */}
                  <div className="stock-balance-grid">
                    <div className="balance-stat-card card-available">
                      <span className="stat-label">AVAILABLE (ATP)</span>
                      <strong className="stat-value">
                        {resolvedEntity.entity.stock_balances?.available ?? 0}
                      </strong>
                      <span className="stat-unit">{resolvedEntity.entity.uom || 'units'}</span>
                    </div>
                    <div className="balance-stat-card card-reserved">
                      <span className="stat-label">RESERVED</span>
                      <strong className="stat-value">
                        {resolvedEntity.entity.stock_balances?.reserved ?? 0}
                      </strong>
                      <span className="stat-unit">{resolvedEntity.entity.uom || 'units'}</span>
                    </div>
                    <div className="balance-stat-card card-quarantined">
                      <span className="stat-label">QUARANTINED</span>
                      <strong className="stat-value">
                        {resolvedEntity.entity.stock_balances?.quarantined ?? 0}
                      </strong>
                      <span className="stat-unit">{resolvedEntity.entity.uom || 'units'}</span>
                    </div>
                    <div className="balance-stat-card card-transit">
                      <span className="stat-label">IN TRANSIT</span>
                      <strong className="stat-value">
                        {resolvedEntity.entity.stock_balances?.in_transit ?? 0}
                      </strong>
                      <span className="stat-unit">{resolvedEntity.entity.uom || 'units'}</span>
                    </div>
                  </div>

                  {/* Location Balances */}
                  {resolvedEntity.entity.location_balances && resolvedEntity.entity.location_balances.length > 0 && (
                    <div className="location-balances-section">
                      <h4>Location Stock Balances</h4>
                      <table className="portal-table">
                        <thead>
                          <tr>
                            <th>Warehouse</th>
                            <th>Location / Bin</th>
                            <th>Stock Type</th>
                            <th>Quantity</th>
                          </tr>
                        </thead>
                        <tbody>
                          {resolvedEntity.entity.location_balances.map((lb, idx) => (
                            <tr key={idx}>
                              <td>{lb.warehouse_name || `WH-${lb.warehouse_id}`}</td>
                              <td><MapPin size={12} /> {lb.location_code}</td>
                              <td><span className="stock-type-pill">{lb.stock_type}</span></td>
                              <td><strong>{lb.quantity}</strong></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Quick Workflow Action Shortcuts */}
                  <div className="portal-quick-actions">
                    <button
                      className="portal-action-btn"
                      onClick={() => {
                        setActiveTab('transfer')
                        setTransferState((prev) => ({
                          ...prev,
                          productId: resolvedEntity.entity.id,
                          productSku: resolvedEntity.entity.sku,
                          productName: resolvedEntity.entity.name,
                          atpAvailable: resolvedEntity.entity.stock_balances?.available ?? 0,
                        }))
                      }}
                    >
                      <ArrowRightLeft size={14} />
                      <span>Transfer This SKU</span>
                    </button>
                    <button
                      className="portal-action-btn"
                      onClick={() => {
                        setActiveTab('labels')
                        setLabelForm((prev) => ({
                          ...prev,
                          entity_type: 'PRODUCT',
                          entity_id: resolvedEntity.entity.id,
                        }))
                      }}
                    >
                      <Printer size={14} />
                      <span>Print SKU Label</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Entity: LOCATION */}
              {resolvedEntity.entity_type === 'LOCATION' && (
                <div className="entity-detail-body">
                  <div className="entity-title-row">
                    <div>
                      <h2>Bin Location: {resolvedEntity.entity.location_code}</h2>
                      <div className="entity-sub-meta">
                        <span>Warehouse: <strong>{resolvedEntity.entity.warehouse_name || `WH-${resolvedEntity.entity.warehouse_id}`}</strong></span>
                        <span>Zone: <strong>{resolvedEntity.entity.zone || 'N/A'}</strong></span>
                        <span>Rack: <strong>{resolvedEntity.entity.rack || 'N/A'}</strong></span>
                        <span>Shelf: <strong>{resolvedEntity.entity.shelf || 'N/A'}</strong></span>
                        <span>Bin: <strong>{resolvedEntity.entity.bin || 'N/A'}</strong></span>
                      </div>
                    </div>
                  </div>

                  <h4>Stock in this Bin</h4>
                  {resolvedEntity.entity.inventory_balances?.length ? (
                    <table className="portal-table">
                      <thead>
                        <tr>
                          <th>Product SKU</th>
                          <th>Product Name</th>
                          <th>Stock Type</th>
                          <th>Quantity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {resolvedEntity.entity.inventory_balances.map((ib, idx) => (
                          <tr key={idx}>
                            <td><strong>{ib.sku}</strong></td>
                            <td>{ib.product_name}</td>
                            <td><span className="stock-type-pill">{ib.stock_type}</span></td>
                            <td>{ib.quantity}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="table-empty-msg">No current stock stored in this bin.</div>
                  )}

                  <div className="portal-quick-actions">
                    <button
                      className="portal-action-btn"
                      onClick={() => {
                        setActiveTab('transfer')
                        setTransferState((prev) => ({
                          ...prev,
                          sourceLocationId: resolvedEntity.entity.id,
                          sourceLocationCode: resolvedEntity.entity.location_code,
                        }))
                      }}
                    >
                      <ArrowRightLeft size={14} />
                      <span>Transfer From This Bin</span>
                    </button>
                    <button
                      className="portal-action-btn"
                      onClick={() => {
                        setActiveTab('labels')
                        setLabelForm((prev) => ({
                          ...prev,
                          entity_type: 'LOCATION',
                          entity_id: resolvedEntity.entity.id,
                          label_size: '2x1',
                        }))
                      }}
                    >
                      <Printer size={14} />
                      <span>Print Bin Shelf Label</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Entity: PURCHASE ORDER */}
              {resolvedEntity.entity_type === 'PURCHASE_ORDER' && (
                <div className="entity-detail-body">
                  <div className="entity-title-row">
                    <div>
                      <h2>Purchase Order: {resolvedEntity.entity.po_number || resolvedEntity.entity.id}</h2>
                      <div className="entity-sub-meta">
                        <span>Supplier: <strong>{resolvedEntity.entity.supplier_name || 'N/A'}</strong></span>
                        <span>Status: <strong>{resolvedEntity.entity.status}</strong></span>
                        <span>Total: <strong>${resolvedEntity.entity.grand_total?.toFixed(2) || '0.00'}</strong></span>
                      </div>
                    </div>
                  </div>

                  <h4>PO Line Items</h4>
                  <table className="portal-table">
                    <thead>
                      <tr>
                        <th>Product / SKU</th>
                        <th>Ordered</th>
                        <th>Received</th>
                        <th>Remaining</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(resolvedEntity.entity.line_items || []).map((li, idx) => (
                        <tr key={idx}>
                          <td>
                            <strong>{li.sku || `SKU-${li.product_id}`}</strong>
                            <div className="table-subtext">{li.product_name}</div>
                          </td>
                          <td>{li.ordered_qty}</td>
                          <td>{li.received_qty || 0}</td>
                          <td>
                            <strong className="text-amber">
                              {Math.max(0, (li.ordered_qty || 0) - (li.received_qty || 0))}
                            </strong>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  <div className="portal-quick-actions">
                    <button
                      className="portal-action-btn"
                      onClick={() => {
                        setActiveTab('receipt')
                        routeScanByContext(resolvedEntity, resolvedEntity.barcode_value)
                      }}
                    >
                      <Boxes size={14} />
                      <span>Receive Inbound Shipment</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Entity: SALES ORDER */}
              {resolvedEntity.entity_type === 'SALES_ORDER' && (
                <div className="entity-detail-body">
                  <div className="entity-title-row">
                    <div>
                      <h2>Sales Order: {resolvedEntity.entity.order_number || resolvedEntity.entity.id}</h2>
                      <div className="entity-sub-meta">
                        <span>Customer: <strong>{resolvedEntity.entity.customer_name || 'N/A'}</strong></span>
                        <span>Status: <strong>{resolvedEntity.entity.status}</strong></span>
                        <span>Total: <strong>${resolvedEntity.entity.grand_total?.toFixed(2) || '0.00'}</strong></span>
                      </div>
                    </div>
                  </div>

                  <h4>Order Lines &amp; Fulfilment Status</h4>
                  <table className="portal-table">
                    <thead>
                      <tr>
                        <th>Product / SKU</th>
                        <th>Ordered</th>
                        <th>Allocated</th>
                        <th>Picked</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(resolvedEntity.entity.line_items || []).map((li, idx) => (
                        <tr key={idx}>
                          <td>
                            <strong>{li.sku || `SKU-${li.product_id}`}</strong>
                            <div className="table-subtext">{li.product_name}</div>
                          </td>
                          <td>{li.ordered_quantity}</td>
                          <td>{li.allocated_quantity}</td>
                          <td>{li.picked_quantity}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  <div className="portal-quick-actions">
                    <button
                      className="portal-action-btn"
                      onClick={() => {
                        setActiveTab('packing')
                        routeScanByContext(resolvedEntity, resolvedEntity.barcode_value)
                      }}
                    >
                      <Package size={14} />
                      <span>Verify &amp; Pack Order</span>
                    </button>
                  </div>
                </div>
              )}

              {/* Entity: SHIPMENT */}
              {resolvedEntity.entity_type === 'SHIPMENT' && (
                <div className="entity-detail-body">
                  <div className="entity-title-row">
                    <div>
                      <h2>Export Cargo: {resolvedEntity.entity.shipment_number || resolvedEntity.entity.id}</h2>
                      <div className="entity-sub-meta">
                        <span>Destination Port: <strong>{resolvedEntity.entity.destination_port || 'N/A'}</strong></span>
                        <span>Status: <strong>{resolvedEntity.entity.status}</strong></span>
                        <span>Customs Clearance: <strong>{resolvedEntity.entity.customs_clearance_status || 'PENDING'}</strong></span>
                      </div>
                    </div>
                  </div>

                  {/* Readiness Blockers */}
                  <div className="cargo-blockers-box">
                    <h4>Customs Readiness &amp; Document Checklist</h4>
                    {resolvedEntity.entity.readiness_blockers?.length > 0 ? (
                      <div className="blockers-list">
                        {resolvedEntity.entity.readiness_blockers.map((b, idx) => (
                          <div key={idx} className="blocker-item">
                            <AlertTriangle size={14} className="text-rose" />
                            <span>{b}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="blocker-item text-emerald">
                        <CheckCircle2 size={14} />
                        <span>All core export documentation and clearances verified.</span>
                      </div>
                    )}
                  </div>

                  {/* Statutory Disclaimer */}
                  <div className="customs-statutory-notice">
                    <ShieldAlert size={16} />
                    <span>
                      Notice: Barcode/QR scan is for internal warehouse and operational tracking only. Official
                      customs clearance requires verified shipping documentation and authorized regulatory filing.
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* TAB 2: Scan-Driven Inbound Goods Receipt */}
      {activeTab === 'receipt' && (
        <div className="portal-view-section">
          <div className="section-header">
            <div>
              <h3>Inbound Goods Receipt Workflow</h3>
              <p>Step 1: Scan Purchase Order. Step 2: Verify received counts. Step 3: Explicit operator confirmation.</p>
            </div>
          </div>

          {!receiptState.poData ? (
            <div className="portal-empty-state">
              <Boxes size={48} className="empty-icon" />
              <h3>Scan a Purchase Order Barcode to Begin</h3>
              <p>You can scan a PO barcode or enter "TS:v1:PO:&lt;ID&gt;" in the scanner bar above.</p>
              <div className="sample-btn-group">
                <button onClick={() => handleLoadSample('PO')} className="portal-action-btn">
                  Load Sample PO #1
                </button>
              </div>
            </div>
          ) : (
            <div className="workflow-card">
              <div className="workflow-card-top">
                <div>
                  <h4>PO: {receiptState.poData.po_number || receiptState.poData.id}</h4>
                  <span className="text-muted">Supplier: {receiptState.poData.supplier_name || 'N/A'}</span>
                </div>
                <div className="warehouse-target-selector">
                  <label>Receiving Warehouse:</label>
                  <select
                    value={receiptState.targetWarehouseId}
                    onChange={(e) =>
                      setReceiptState((prev) => ({ ...prev, targetWarehouseId: e.target.value }))
                    }
                    className="portal-select"
                  >
                    <option value="">Select Warehouse...</option>
                    {masterWarehouses.map((wh) => (
                      <option key={wh.id} value={wh.id}>
                        {wh.name} ({wh.code})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Line Items Receiving Table */}
              <table className="portal-table receipt-table">
                <thead>
                  <tr>
                    <th>Product / SKU</th>
                    <th>Ordered</th>
                    <th>Prior Received</th>
                    <th>Accepted Qty</th>
                    <th>Rejected Qty</th>
                    <th>Quarantined Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {receiptState.lineItems.map((li, idx) => (
                    <tr key={idx}>
                      <td>
                        <strong>{li.sku}</strong>
                        <div className="table-subtext">{li.product_name}</div>
                      </td>
                      <td>{li.ordered_qty}</td>
                      <td>{li.received_qty}</td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          value={li.accepted_qty}
                          onChange={(e) => {
                            const val = Math.max(0, parseInt(e.target.value) || 0)
                            const next = [...receiptState.lineItems]
                            next[idx].accepted_qty = val
                            setReceiptState((prev) => ({ ...prev, lineItems: next }))
                          }}
                          className="qty-cell-input"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          value={li.rejected_qty}
                          onChange={(e) => {
                            const val = Math.max(0, parseInt(e.target.value) || 0)
                            const next = [...receiptState.lineItems]
                            next[idx].rejected_qty = val
                            setReceiptState((prev) => ({ ...prev, lineItems: next }))
                          }}
                          className="qty-cell-input text-rose"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          value={li.quarantined_qty}
                          onChange={(e) => {
                            const val = Math.max(0, parseInt(e.target.value) || 0)
                            const next = [...receiptState.lineItems]
                            next[idx].quarantined_qty = val
                            setReceiptState((prev) => ({ ...prev, lineItems: next }))
                          }}
                          className="qty-cell-input text-amber"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="workflow-bottom-bar">
                <button
                  className="portal-action-btn btn-secondary"
                  onClick={() => setReceiptState({ poData: null, targetWarehouseId: '', targetLocationId: '', lineItems: [] })}
                >
                  Cancel Receipt
                </button>
                <button
                  className="portal-action-btn btn-primary"
                  onClick={openConfirmReceiptModal}
                >
                  <CheckCircle2 size={16} />
                  <span>Confirm Inbound Posting</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: Scan-Driven Warehouse Location Transfer */}
      {activeTab === 'transfer' && (
        <div className="portal-view-section">
          <div className="section-header">
            <div>
              <h3>Scan-Driven Bin Location Transfer</h3>
              <p>Move inventory safely with continuous ATP and source location verification.</p>
            </div>
          </div>

          <div className="transfer-wizard-grid">
            {/* Step 1: Source Location */}
            <div className={`wizard-card ${transferState.sourceLocationId ? 'completed' : 'active'}`}>
              <div className="wizard-step-header">
                <span className="step-num">1</span>
                <h4>Source Location</h4>
              </div>
              <div className="wizard-body">
                {transferState.sourceLocationId ? (
                  <div className="selected-entity-box">
                    <MapPin size={18} className="text-teal" />
                    <div>
                      <strong>{transferState.sourceLocationCode}</strong>
                      <div className="table-subtext">Location ID: #{transferState.sourceLocationId}</div>
                    </div>
                    <button
                      className="reset-step-btn"
                      onClick={() => setTransferState((prev) => ({ ...prev, sourceLocationId: '', sourceLocationCode: '' }))}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <div className="wizard-prompt">
                    <p>Scan source location barcode or select from list:</p>
                    <select
                      onChange={(e) => {
                        const loc = masterLocations.find((l) => String(l.id) === e.target.value)
                        if (loc) {
                          setTransferState((prev) => ({
                            ...prev,
                            sourceLocationId: loc.id,
                            sourceLocationCode: loc.location_code,
                            sourceWarehouseId: loc.warehouse_id,
                          }))
                        }
                      }}
                      className="portal-select"
                    >
                      <option value="">Select Source Location...</option>
                      {masterLocations.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.location_code} ({l.warehouse_name || `WH-${l.warehouse_id}`})
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            </div>

            {/* Step 2: Product SKU */}
            <div className={`wizard-card ${transferState.productId ? 'completed' : transferState.sourceLocationId ? 'active' : 'disabled'}`}>
              <div className="wizard-step-header">
                <span className="step-num">2</span>
                <h4>Product / SKU</h4>
              </div>
              <div className="wizard-body">
                {transferState.productId ? (
                  <div className="selected-entity-box">
                    <Package size={18} className="text-teal" />
                    <div>
                      <strong>{transferState.productSku}</strong>
                      <div className="table-subtext">{transferState.productName}</div>
                      <div className="text-emerald atp-tag">Available ATP: {transferState.atpAvailable}</div>
                    </div>
                    <button
                      className="reset-step-btn"
                      onClick={() => setTransferState((prev) => ({ ...prev, productId: '', productSku: '', productName: '', atpAvailable: 0 }))}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <div className="wizard-prompt">
                    <p>Scan product barcode or select:</p>
                    <select
                      onChange={(e) => {
                        const prod = masterProducts.find((p) => String(p.id) === e.target.value)
                        if (prod) {
                          setTransferState((prev) => ({
                            ...prev,
                            productId: prod.id,
                            productSku: prod.sku,
                            productName: prod.name,
                            atpAvailable: prod.stock_balances?.available ?? 10,
                          }))
                        }
                      }}
                      className="portal-select"
                      disabled={!transferState.sourceLocationId}
                    >
                      <option value="">Select Product...</option>
                      {masterProducts.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.sku} - {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            </div>

            {/* Step 3: Target Location */}
            <div className={`wizard-card ${transferState.targetLocationId ? 'completed' : transferState.productId ? 'active' : 'disabled'}`}>
              <div className="wizard-step-header">
                <span className="step-num">3</span>
                <h4>Destination Location</h4>
              </div>
              <div className="wizard-body">
                {transferState.targetLocationId ? (
                  <div className="selected-entity-box">
                    <MapPin size={18} className="text-teal" />
                    <div>
                      <strong>{transferState.targetLocationCode}</strong>
                      <div className="table-subtext">Location ID: #{transferState.targetLocationId}</div>
                    </div>
                    <button
                      className="reset-step-btn"
                      onClick={() => setTransferState((prev) => ({ ...prev, targetLocationId: '', targetLocationCode: '' }))}
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <div className="wizard-prompt">
                    <p>Scan destination location barcode:</p>
                    <select
                      onChange={(e) => {
                        const loc = masterLocations.find((l) => String(l.id) === e.target.value)
                        if (loc) {
                          setTransferState((prev) => ({
                            ...prev,
                            targetLocationId: loc.id,
                            targetLocationCode: loc.location_code,
                            targetWarehouseId: loc.warehouse_id,
                          }))
                        }
                      }}
                      className="portal-select"
                      disabled={!transferState.productId}
                    >
                      <option value="">Select Destination Location...</option>
                      {masterLocations
                        .filter((l) => l.id !== transferState.sourceLocationId)
                        .map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.location_code} ({l.warehouse_name || `WH-${l.warehouse_id}`})
                          </option>
                        ))}
                    </select>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Transfer Execution Controls */}
          {transferState.sourceLocationId && transferState.productId && transferState.targetLocationId && (
            <div className="transfer-summary-card">
              <div className="transfer-summary-inputs">
                <div>
                  <label>Transfer Quantity:</label>
                  <input
                    type="number"
                    min="1"
                    max={transferState.atpAvailable || 9999}
                    value={transferState.transferQty}
                    onChange={(e) =>
                      setTransferState((prev) => ({ ...prev, transferQty: Math.max(1, parseInt(e.target.value) || 1) }))
                    }
                    className="portal-qty-input"
                  />
                  <span className="input-helper">Max available: {transferState.atpAvailable}</span>
                </div>
                <div>
                  <label>Operator Notes:</label>
                  <input
                    type="text"
                    value={transferState.notes}
                    onChange={(e) => setTransferState((prev) => ({ ...prev, notes: e.target.value }))}
                    placeholder="e.g. Rack consolidation / Bin re-slotting"
                    className="portal-notes-input"
                  />
                </div>
              </div>

              <div className="transfer-action-row">
                <button
                  className="portal-action-btn btn-primary"
                  onClick={openConfirmTransferModal}
                >
                  <ArrowRightLeft size={16} />
                  <span>Confirm Bin Transfer</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: Sales Pick & Pack Verification */}
      {activeTab === 'packing' && (
        <div className="portal-view-section">
          <div className="section-header">
            <div>
              <h3>Sales Fulfilment Pick &amp; Pack</h3>
              <p>Scan Sales Order, scan SKUs into dispatch cartons, prevent over-packing beyond allocated quantities.</p>
            </div>
          </div>

          {!packingState.soData ? (
            <div className="portal-empty-state">
              <Package size={48} className="empty-icon" />
              <h3>Scan a Sales Order Barcode to Begin Packing</h3>
              <div className="sample-btn-group">
                <button onClick={() => handleLoadSample('SO')} className="portal-action-btn">
                  Load Sample SO #1
                </button>
              </div>
            </div>
          ) : (
            <div className="workflow-card">
              <div className="workflow-card-top">
                <div>
                  <h4>SO: {packingState.soData.order_number || packingState.soData.id}</h4>
                  <span className="text-muted">Customer: {packingState.soData.customer_name || 'N/A'}</span>
                </div>
                <div className="package-tag-input">
                  <label>Target Package #:</label>
                  <input
                    type="text"
                    value={packingState.targetPackageNumber}
                    onChange={(e) =>
                      setPackingState((prev) => ({ ...prev, targetPackageNumber: e.target.value }))
                    }
                    className="portal-operator-input"
                  />
                </div>
              </div>

              <table className="portal-table packing-table">
                <thead>
                  <tr>
                    <th>Product / SKU</th>
                    <th>Ordered</th>
                    <th>Allocated</th>
                    <th>Prior Picked</th>
                    <th>Qty to Pack Now</th>
                    <th>Verification</th>
                  </tr>
                </thead>
                <tbody>
                  {packingState.lines.map((li, idx) => {
                    const remainingToPack = Math.max(0, li.allocated_qty - li.picked_qty)
                    const isFullyPacked = remainingToPack === 0
                    return (
                      <tr key={idx} className={isFullyPacked ? 'row-completed' : ''}>
                        <td>
                          <strong>{li.sku}</strong>
                          <div className="table-subtext">{li.product_name}</div>
                        </td>
                        <td>{li.ordered_qty}</td>
                        <td>{li.allocated_qty}</td>
                        <td>{li.picked_qty}</td>
                        <td>
                          <input
                            type="number"
                            min="0"
                            max={remainingToPack}
                            value={li.pack_input}
                            disabled={isFullyPacked}
                            onChange={(e) => {
                              const val = Math.min(remainingToPack, Math.max(0, parseInt(e.target.value) || 0))
                              const next = [...packingState.lines]
                              next[idx].pack_input = val
                              setPackingState((prev) => ({ ...prev, lines: next }))
                            }}
                            className="qty-cell-input"
                          />
                        </td>
                        <td>
                          {isFullyPacked ? (
                            <span className="status-pill status-ready">COMPLETE</span>
                          ) : (
                            <span className="status-pill status-pending">PENDING ({remainingToPack} REMAINING)</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>

              <div className="workflow-bottom-bar">
                <button
                  className="portal-action-btn btn-secondary"
                  onClick={() => setPackingState({ soData: null, lines: [], targetPackageNumber: '' })}
                >
                  Cancel
                </button>
                <button
                  className="portal-action-btn btn-primary"
                  onClick={openConfirmPackModal}
                >
                  <ClipboardCheck size={16} />
                  <span>Confirm Packing Verification</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 5: Export Cargo & Customs Lookup */}
      {activeTab === 'cargo' && (
        <div className="portal-view-section">
          <div className="section-header">
            <div>
              <h3>Export Cargo &amp; Customs Readiness Station</h3>
              <p>Cross-reference container dispatches with required international shipping documents.</p>
            </div>
          </div>

          <div className="cargo-search-card">
            <p>Scan Export Shipment or Package barcode, or select sample:</p>
            <div className="sample-btn-group">
              <button onClick={() => handleLoadSample('SHIPMENT')} className="portal-action-btn">
                Load Sample Shipment #1
              </button>
            </div>
          </div>

          {/* Statutory Disclaimer Always Displayed in Cargo Tab */}
          <div className="customs-statutory-notice">
            <ShieldAlert size={18} />
            <div>
              <strong>Statutory Customs Verification Disclaimer</strong>
              <p>
                Barcode &amp; QR scans in this portal provide internal operational and inventory tracking only.
                Under international maritime and trade regulations, customs clearance strictly requires official,
                digitally signed Commercial Invoices, Packing Lists, Certificates of Origin, and regulatory filings.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* TAB 6: Label Station (Printable 4"x2" and 2"x1" Thermal Labels) */}
      {activeTab === 'labels' && (
        <div className="portal-view-section">
          <div className="section-header">
            <div>
              <h3>Printable Thermal Label Station</h3>
              <p>Generate ISO/IEC compliant 4"x2" (Pallet/Carton) and 2"x1" (Bin/SKU) thermal labels.</p>
            </div>
          </div>

          <div className="label-station-grid">
            {/* Generator Form */}
            <div className="label-form-card">
              <h4>Create New Operational Label</h4>

              <div className="form-group">
                <label>Entity Type:</label>
                <select
                  value={labelForm.entity_type}
                  onChange={(e) => setLabelForm((prev) => ({ ...prev, entity_type: e.target.value }))}
                  className="portal-select"
                >
                  <option value="PRODUCT">Product / SKU</option>
                  <option value="LOCATION">Warehouse Location / Bin</option>
                  <option value="PURCHASE_ORDER">Purchase Order</option>
                  <option value="GOODS_RECEIPT">Goods Receipt</option>
                  <option value="SALES_ORDER">Sales Order</option>
                  <option value="SHIPMENT">Export Shipment</option>
                  <option value="PACKAGE">Dispatch Package</option>
                </select>
              </div>

              <div className="form-group">
                <label>Select Master Record or Entity ID:</label>
                {labelForm.entity_type === 'PRODUCT' ? (
                  <select
                    value={labelForm.entity_id}
                    onChange={(e) => setLabelForm((prev) => ({ ...prev, entity_id: e.target.value }))}
                    className="portal-select"
                  >
                    <option value="">Select Product...</option>
                    {masterProducts.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.sku} - {p.name}
                      </option>
                    ))}
                  </select>
                ) : labelForm.entity_type === 'LOCATION' ? (
                  <select
                    value={labelForm.entity_id}
                    onChange={(e) => setLabelForm((prev) => ({ ...prev, entity_id: e.target.value }))}
                    className="portal-select"
                  >
                    <option value="">Select Location...</option>
                    {masterLocations.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.location_code} ({l.warehouse_name || `WH-${l.warehouse_id}`})
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={labelForm.entity_id}
                    onChange={(e) => setLabelForm((prev) => ({ ...prev, entity_id: e.target.value }))}
                    placeholder="Enter ID (e.g. 1)"
                    className="portal-operator-input"
                  />
                )}
              </div>

              <div className="form-group">
                <label>Label Dimension Layout:</label>
                <div className="radio-group-horizontal">
                  <label className="radio-pill">
                    <input
                      type="radio"
                      name="label_size"
                      value="4x2"
                      checked={labelForm.label_size === '4x2'}
                      onChange={() => setLabelForm((prev) => ({ ...prev, label_size: '4x2' }))}
                    />
                    <span>4" x 2" (Standard Shipping / Carton)</span>
                  </label>
                  <label className="radio-pill">
                    <input
                      type="radio"
                      name="label_size"
                      value="2x1"
                      checked={labelForm.label_size === '2x1'}
                      onChange={() => setLabelForm((prev) => ({ ...prev, label_size: '2x1' }))}
                    />
                    <span>2" x 1" (Shelf Bin / Item Tag)</span>
                  </label>
                </div>
              </div>

              <div className="form-group">
                <label>Symbology:</label>
                <select
                  value={labelForm.symbology}
                  onChange={(e) => setLabelForm((prev) => ({ ...prev, symbology: e.target.value }))}
                  className="portal-select"
                >
                  <option value="BOTH">Dual Symbology (QR Code + Code 128)</option>
                  <option value="QR_CODE">QR Code Only</option>
                  <option value="CODE128">Code 128 Barcode Only</option>
                </select>
              </div>

              <button
                className="portal-action-btn btn-primary"
                onClick={handleGenerateLabel}
                disabled={labelLoading || !labelForm.entity_id}
              >
                {labelLoading ? <RefreshCw className="spin" size={16} /> : <Printer size={16} />}
                <span>Generate &amp; Preview Label</span>
              </button>
            </div>

            {/* Live Label Preview */}
            <div className="label-preview-card">
              <div className="preview-header">
                <h4>Thermal Print Preview</h4>
                {labelPreviewHtml && (
                  <button className="portal-action-btn btn-print" onClick={handlePrintIframe}>
                    <Printer size={14} />
                    <span>Print Thermal Label</span>
                  </button>
                )}
              </div>

              {labelPreviewHtml ? (
                <div className="iframe-preview-container">
                  <iframe
                    id="label-print-iframe"
                    title="Label Preview"
                    srcDoc={labelPreviewHtml}
                    className="thermal-preview-frame"
                  />
                </div>
              ) : (
                <div className="preview-empty-state">
                  <Printer size={40} className="empty-icon" />
                  <p>Generate a label or select one from recent labels below to preview.</p>
                </div>
              )}
            </div>
          </div>

          {/* Recent Labels List */}
          <div className="recent-labels-card">
            <h4>Recently Generated Labels</h4>
            {recentLabels.length === 0 ? (
              <div className="table-empty-msg">No labels generated yet.</div>
            ) : (
              <table className="portal-table">
                <thead>
                  <tr>
                    <th>Barcode Value</th>
                    <th>Entity Type</th>
                    <th>Size</th>
                    <th>Symbology</th>
                    <th>Created</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {recentLabels.map((lbl) => (
                    <tr key={lbl.id}>
                      <td><strong>{lbl.barcode_value}</strong></td>
                      <td><span className="entity-type-badge">{lbl.entity_type}</span></td>
                      <td>{lbl.label_size || '4x2'}</td>
                      <td>{lbl.symbology}</td>
                      <td>{lbl.created_at ? new Date(lbl.created_at).toLocaleString() : 'N/A'}</td>
                      <td>
                        {lbl.is_active ? (
                          <span className="status-pill status-ready">ACTIVE</span>
                        ) : (
                          <span className="status-pill status-inactive">DEACTIVATED</span>
                        )}
                      </td>
                      <td>
                        <div className="row-action-btns">
                          <button
                            className="btn-tiny"
                            onClick={() => handlePreviewLabel(lbl.id)}
                            title="Preview Label"
                          >
                            <Eye size={14} />
                          </button>
                          {lbl.is_active ? (
                            <button
                              className="btn-tiny text-rose"
                              onClick={() => handleDeactivateLabel(lbl.id)}
                              title="Deactivate Label"
                            >
                              <XCircle size={14} />
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* CAMERA SCANNER MODAL */}
      {isCameraOpen && (
        <div className="portal-modal-backdrop">
          <div className="camera-modal-content">
            <div className="camera-modal-header">
              <div className="camera-header-title">
                <Camera size={18} />
                <span>Live Barcode &amp; QR Scanner</span>
              </div>
              <button className="camera-modal-close" onClick={closeCamera}>
                <X size={18} />
              </button>
            </div>

            <div className="camera-modal-body">
              {cameraError ? (
                <div className="camera-error-banner">
                  <AlertTriangle size={20} />
                  <div>
                    <p>{cameraError}</p>
                    <small>You can still use any handheld USB/Bluetooth barcode scanner gun.</small>
                  </div>
                </div>
              ) : (
                <div className="scanner-viewport-wrapper">
                  <div id="portal-qr-reader" className="scanner-html5-element" />
                  <div className="scanner-reticle" />
                </div>
              )}

              {camerasList.length > 1 && (
                <div className="camera-switch-row">
                  <label>Camera Device:</label>
                  <select
                    value={selectedCameraId}
                    onChange={(e) => {
                      setSelectedCameraId(e.target.value)
                      initHtml5Scanner(e.target.value)
                    }}
                    className="portal-select"
                  >
                    {camerasList.map((cam) => (
                      <option key={cam.id} value={cam.id}>
                        {cam.label || `Camera ${cam.id}`}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="camera-modal-footer">
              <span className="camera-tip">Point camera at 1D Barcode (Code 128) or 2D QR Code</span>
              <button className="portal-action-btn btn-secondary" onClick={closeCamera}>
                Close Camera
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CONFIRMATION DIALOG (Non-negotiable ERP safety rule) */}
      {confirmModal.isOpen && (
        <div className="portal-modal-backdrop">
          <div className="confirm-modal-content">
            <div className="confirm-modal-header">
              <ShieldAlert size={22} className="text-amber" />
              <h3>{confirmModal.title}</h3>
            </div>
            <div className="confirm-modal-body">
              <div className="safety-warning-banner">
                <strong>CRITICAL INVENTORY MUTATION CHECK</strong>
                <p>
                  TradeSathi ERP policy requires explicit operator confirmation before inventory ledgers are updated.
                </p>
              </div>
              <p className="confirm-modal-msg">{confirmModal.message}</p>
              <div className="operator-signature-note">
                Action will be audited as performed by: <strong>{operatorName}</strong> ({currentRole})
              </div>
            </div>
            <div className="confirm-modal-footer">
              <button
                className="portal-action-btn btn-secondary"
                onClick={() => setConfirmModal({ isOpen: false, title: '', message: '', actionType: null, payload: null })}
                disabled={loading}
              >
                Cancel
              </button>
              <button
                className="portal-action-btn btn-confirm-mutate"
                onClick={executeConfirmedAction}
                disabled={loading}
              >
                {loading ? <RefreshCw className="spin" size={16} /> : <Check size={16} />}
                <span>Confirm &amp; Post Ledger</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
