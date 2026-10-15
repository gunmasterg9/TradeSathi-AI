/**
 * TradeSathi AI — CBM & Cargo Volume / Weight Calculation Helper
 * High-precision mathematical conversions and container capacity estimation.
 */

export const M_TO_CM = 100
export const M_TO_MM = 1000
export const INCH_TO_M = 0.0254
export const FOOT_TO_M = 0.3048
export const CBM_TO_CUFT = 35.3146667
export const KG_TO_LB = 2.2046226218

export const DEFAULT_CONTAINERS = [
  {
    key: '20ft_std',
    name: '20 ft Standard Dry Container',
    length_m: 5.90,
    width_m: 2.35,
    height_m: 2.39,
    nominal_cbm: 33.14,
    default_payload_kg: null,
  },
  {
    key: '40ft_std',
    name: '40 ft Standard Dry Container',
    length_m: 12.03,
    width_m: 2.35,
    height_m: 2.39,
    nominal_cbm: 67.58,
    default_payload_kg: null,
  },
  {
    key: '40ft_hc',
    name: '40 ft High-Cube Container',
    length_m: 12.03,
    width_m: 2.35,
    height_m: 2.69,
    nominal_cbm: 76.06,
    default_payload_kg: null,
  },
]

export const CONTAINER_DISCLAIMER =
  'Simplified geometric and volumetric grid estimate. Real loading depends on palletization, ' +
  'structural stacking strength, door openings, cargo distribution, and lashing clearances. ' +
  'Mixed cargo packing requires a dedicated load plan.'

/**
 * Convert length/width/height to meters.
 */
export function normalizeDimensionToMeters(val, unit) {
  const num = Number(val)
  if (isNaN(num) || !isFinite(num) || num <= 0) {
    throw new Error(`Dimension must be a positive finite number, got ${val}`)
  }
  const u = (unit || 'cm').trim().toLowerCase()
  switch (u) {
    case 'm':
    case 'meter':
    case 'meters':
      return num
    case 'cm':
    case 'centimeter':
    case 'centimeters':
      return num / M_TO_CM
    case 'mm':
    case 'millimeter':
    case 'millimeters':
      return num / M_TO_MM
    case 'in':
    case 'inch':
    case 'inches':
      return num * INCH_TO_M
    case 'ft':
    case 'foot':
    case 'feet':
      return num * FOOT_TO_M
    default:
      throw new Error(`Unsupported dimension unit '${unit}'`)
  }
}

/**
 * Convert weight to kilograms.
 */
export function normalizeWeightToKg(val, unit) {
  const num = Number(val)
  if (isNaN(num) || !isFinite(num) || num < 0) {
    throw new Error(`Gross weight must be a non-negative finite number, got ${val}`)
  }
  const u = (unit || 'kg').trim().toLowerCase()
  switch (u) {
    case 'kg':
    case 'kilogram':
    case 'kilograms':
      return num
    case 'lb':
    case 'lbs':
    case 'pound':
    case 'pounds':
      return num / KG_TO_LB
    default:
      throw new Error(`Unsupported weight unit '${unit}'`)
  }
}

/**
 * Convert kg to pounds.
 */
export function convertKgToLb(kg) {
  return kg * KG_TO_LB
}

/**
 * Convert CBM to cubic feet.
 */
export function convertCbmToCuft(cbm) {
  return cbm * CBM_TO_CUFT
}

/**
 * Calculate metrics for a single cargo line.
 */
export function calculateCargoLine(line, dimensionalDivisor = 6000) {
  const lengthM = normalizeDimensionToMeters(line.length, line.dimension_unit)
  const widthM = normalizeDimensionToMeters(line.width, line.dimension_unit)
  const heightM = normalizeDimensionToMeters(line.height, line.dimension_unit)
  const weightKg = normalizeWeightToKg(line.gross_weight_per_pkg || 0, line.weight_unit || 'kg')
  const qty = parseInt(line.quantity, 10)
  if (isNaN(qty) || qty < 1) {
    throw new Error(`Quantity must be a positive integer, got ${line.quantity}`)
  }

  const cbmPerPkg = lengthM * widthM * heightM
  const totalCbm = cbmPerPkg * qty
  const totalCuft = totalCbm * CBM_TO_CUFT
  const totalWeightKg = weightKg * qty
  const totalWeightLb = totalWeightKg * KG_TO_LB

  // Volumetric weight (kg) = (L_cm * W_cm * H_cm / divisor) * qty
  const lCm = lengthM * 100
  const wCm = widthM * 100
  const hCm = heightM * 100
  const volWeightPerPkg = (lCm * wCm * hCm) / Number(dimensionalDivisor)
  const totalVolWeight = volWeightPerPkg * qty

  return {
    description: line.description || 'Cargo Item',
    sku: line.sku || '',
    package_type: line.package_type || 'carton',
    quantity: qty,
    length_orig: Number(line.length),
    width_orig: Number(line.width),
    height_orig: Number(line.height),
    dimension_unit: line.dimension_unit || 'cm',
    gross_weight_orig: Number(line.gross_weight_per_pkg || 0),
    weight_unit: line.weight_unit || 'kg',
    length_m: lengthM,
    width_m: widthM,
    height_m: heightM,
    weight_kg: weightKg,
    cbm_per_pkg: cbmPerPkg,
    total_cbm: totalCbm,
    total_cuft: totalCuft,
    total_gross_weight_kg: totalWeightKg,
    total_gross_weight_lb: totalWeightLb,
    volumetric_weight_kg: totalVolWeight,
    notes: line.notes || '',
  }
}

/**
 * Calculate aggregate totals across multiple cargo lines.
 */
export function calculateCargoAggregate(lines, freightMode = 'general', dimensionalDivisor = 6000, perPkgRounding = false) {
  if (!lines || lines.length === 0) {
    return {
      total_packages: 0,
      total_cbm: 0,
      total_cuft: 0,
      total_gross_weight_kg: 0,
      total_gross_weight_lb: 0,
      total_volumetric_weight_kg: 0,
      chargeable_weight_kg: 0,
      dimensional_divisor_used: dimensionalDivisor,
      freight_mode: freightMode,
      average_cbm_per_pkg: 0,
      average_weight_kg_per_pkg: 0,
      smallest_cbm_pkg: 0,
      largest_cbm_pkg: 0,
      lines: [],
    }
  }

  const computedLines = lines.map((l) => calculateCargoLine(l, dimensionalDivisor))
  let totalPkgs = 0
  let totalCbm = 0
  let totalWeightKg = 0
  let totalVolWeightKg = 0

  let minCbm = Infinity
  let maxCbm = -Infinity

  for (const item of computedLines) {
    totalPkgs += item.quantity
    totalCbm += item.total_cbm
    totalWeightKg += item.total_gross_weight_kg
    totalVolWeightKg += item.volumetric_weight_kg

    if (item.cbm_per_pkg < minCbm) minCbm = item.cbm_per_pkg
    if (item.cbm_per_pkg > maxCbm) maxCbm = item.cbm_per_pkg
  }

  const totalCuft = totalCbm * CBM_TO_CUFT
  const totalWeightLb = totalWeightKg * KG_TO_LB

  let chargeableWeight = 0
  if (perPkgRounding) {
    for (const item of computedLines) {
      chargeableWeight += Math.max(item.total_gross_weight_kg, item.volumetric_weight_kg)
    }
  } else {
    chargeableWeight = Math.max(totalWeightKg, totalVolWeightKg)
  }

  return {
    total_packages: totalPkgs,
    total_cbm: totalCbm,
    total_cuft: totalCuft,
    total_gross_weight_kg: totalWeightKg,
    total_gross_weight_lb: totalWeightLb,
    total_volumetric_weight_kg: totalVolWeightKg,
    chargeable_weight_kg: chargeableWeight,
    dimensional_divisor_used: Number(dimensionalDivisor),
    freight_mode: freightMode,
    average_cbm_per_pkg: totalPkgs > 0 ? totalCbm / totalPkgs : 0,
    average_weight_kg_per_pkg: totalPkgs > 0 ? totalWeightKg / totalPkgs : 0,
    smallest_cbm_pkg: minCbm === Infinity ? 0 : minCbm,
    largest_cbm_pkg: maxCbm === -Infinity ? 0 : maxCbm,
    lines: computedLines,
  }
}

/**
 * Estimate container capacity for a given package dimension and weight.
 */
export function estimateContainerCapacity(pkgLengthM, pkgWidthM, pkgHeightM, pkgWeightKg = 0, usableRatio = 0.85, customPayloadKg = null, container = null) {
  const targetContainer = container || DEFAULT_CONTAINERS[0]
  const usableVolume = targetContainer.nominal_cbm * usableRatio
  const pkgCbm = pkgLengthM * pkgWidthM * pkgHeightM

  const unitsByVolume = pkgCbm > 0 ? Math.floor(usableVolume / pkgCbm) : 0

  // 6 spatial permutations of package dimensions
  const dims = [pkgLengthM, pkgWidthM, pkgHeightM]
  const orientations = [
    [dims[0], dims[1], dims[2]],
    [dims[0], dims[2], dims[1]],
    [dims[1], dims[0], dims[2]],
    [dims[1], dims[2], dims[0]],
    [dims[2], dims[0], dims[1]],
    [dims[2], dims[1], dims[0]],
  ]

  let bestGrid = 0
  let bestOrientation = null

  for (const [l, w, h] of orientations) {
    if (l <= targetContainer.length_m && w <= targetContainer.width_m && h <= targetContainer.height_m) {
      const fitL = Math.floor(targetContainer.length_m / l)
      const fitW = Math.floor(targetContainer.width_m / w)
      const fitH = Math.floor(targetContainer.height_m / h)
      const totalUnits = fitL * fitW * fitH
      if (totalUnits > bestGrid) {
        bestGrid = totalUnits
        bestOrientation = [l, w, h]
      }
    }
  }

  const doesFit = bestGrid > 0
  const cargoCbm = bestGrid * pkgCbm
  const volumeUtilPct = targetContainer.nominal_cbm > 0 ? (cargoCbm / targetContainer.nominal_cbm) * 100 : 0
  const remainingUsableCbm = Math.max(0, usableVolume - cargoCbm)
  const estCargoWeightKg = bestGrid * pkgWeightKg

  let payloadFeasibility = 'Unknown'
  const payloadLimit = customPayloadKg !== null ? customPayloadKg : targetContainer.default_payload_kg
  if (payloadLimit !== null && payloadLimit > 0) {
    payloadFeasibility = estCargoWeightKg <= payloadLimit ? 'Pass' : 'Exceeds Payload'
  }

  return {
    container_key: targetContainer.key,
    container_name: targetContainer.name,
    internal_length_m: targetContainer.length_m,
    internal_width_m: targetContainer.width_m,
    internal_height_m: targetContainer.height_m,
    nominal_volume_cbm: targetContainer.nominal_cbm,
    usable_ratio: usableRatio,
    usable_volume_cbm: usableVolume,
    cargo_cbm: cargoCbm,
    volume_utilization_pct: volumeUtilPct,
    remaining_usable_cbm: remainingUsableCbm,
    estimated_units_by_volume: unitsByVolume,
    estimated_units_by_grid: bestGrid,
    best_orientation: bestOrientation,
    does_fit_geometrically: doesFit,
    estimated_cargo_weight_at_grid_kg: estCargoWeightKg,
    payload_capacity_kg: payloadLimit,
    payload_feasibility: payloadFeasibility,
    limitation_notes: CONTAINER_DISCLAIMER,
  }
}

/**
 * Format numbers cleanly for UI display.
 */
export function formatDec(num, decimals = 3) {
  if (num === null || num === undefined || isNaN(num)) return '0.000'
  return Number(num).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/**
 * Generate CSV text from cargo lines and totals.
 */
export function generateCargoCsv(calcSummary, title = 'Cargo Calculation') {
  const headers = [
    'Line',
    'Description',
    'SKU',
    'Package Type',
    'Qty',
    'Length',
    'Width',
    'Height',
    'Dim Unit',
    'Weight/Pkg',
    'Weight Unit',
    'CBM/Pkg',
    'Total CBM',
    'Total CuFt',
    'Total Weight (kg)',
    'Total Weight (lb)',
    'Volumetric Weight (kg)',
    'Notes',
  ]

  const rows = (calcSummary.lines || []).map((l, idx) => [
    idx + 1,
    `"${(l.description || '').replace(/"/g, '""')}"`,
    `"${(l.sku || '').replace(/"/g, '""')}"`,
    l.package_type,
    l.quantity,
    l.length_orig,
    l.width_orig,
    l.height_orig,
    l.dimension_unit,
    l.gross_weight_orig,
    l.weight_unit,
    l.cbm_per_pkg.toFixed(4),
    l.total_cbm.toFixed(4),
    l.total_cuft.toFixed(2),
    l.total_gross_weight_kg.toFixed(2),
    l.total_gross_weight_lb.toFixed(2),
    l.volumetric_weight_kg.toFixed(2),
    `"${(l.notes || '').replace(/"/g, '""')}"`,
  ])

  const totals = [
    '',
    '"TOTALS / AGGREGATE"',
    '',
    '',
    calcSummary.total_packages,
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    calcSummary.total_cbm.toFixed(4),
    calcSummary.total_cuft.toFixed(2),
    calcSummary.total_gross_weight_kg.toFixed(2),
    calcSummary.total_gross_weight_lb.toFixed(2),
    calcSummary.total_volumetric_weight_kg.toFixed(2),
    `"Chargeable Weight: ${calcSummary.chargeable_weight_kg.toFixed(2)} kg | Mode: ${calcSummary.freight_mode}"`,
  ]

  return [
    `# TradeSathi AI Cargo Calculation: ${title}`,
    `# Mode: ${calcSummary.freight_mode} | Divisor: ${calcSummary.dimensional_divisor_used} cm3/kg`,
    headers.join(','),
    ...rows.map((r) => r.join(',')),
    totals.join(','),
  ].join('\n')
}
