const API_BASE = `${window.location.protocol}//${window.location.hostname}:8008`;
const OMS_ORDER_PATH = "/api/oms/orders";

const state = {
  mode: "home",
  customer: null,
  customerStores: [],
  selectedStoreIndex: -1,
  lines: [],
  lookups: {
    orderTypes: [],
    sales: [],
  },
  customerLookup: {
    lastQuery: "",
    lastSuccessQuery: "",
    pending: null,
  },
  customerDetail: {
    customer: null,
    orders: [],
    purchases: [],
  },
  busy: {
    lookup: false,
    save: false,
    print: false,
  },
  previewSeq: 0,
  discountMode: "percent",
  writeEnabled: true,
};

const el = (id) => document.getElementById(id);
const valueOf = (id) => el(id)?.value || "";

function money(value) {
  return Number(value || 0).toFixed(2);
}

function qtyDisplay(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "";
  return Number(number.toFixed(4)).toString();
}

function isEditingField(id) {
  return document.activeElement === el(id);
}

function normalizeEmptyZeroField(id) {
  const target = el(id);
  if (!target) return;
  if (String(target.value || "").trim() === "") {
    target.value = "0.00";
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStatus(message, isError = false) {
  const target = el("statusText");
  if (!target) return;
  target.textContent = message;
  target.style.color = isError ? "#b42318" : "#5c6670";
}

function setCustomerHint(message = "", isError = false) {
  const target = el("customerHint");
  target.textContent = message;
  target.classList.toggle("is-error", isError);
}

function setOrderLookupHint(message = "", isError = false) {
  const target = el("orderLookupHint");
  target.textContent = message;
  target.classList.toggle("is-error", isError);
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the HTTP status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

function todayIso() {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function fillSelect(select, items, valueField, labelField, blankLabel = "") {
  select.innerHTML = "";
  if (blankLabel) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = blankLabel;
    select.appendChild(option);
  }
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item[valueField] ?? "";
    option.textContent = item[labelField] || item[valueField] || "";
    select.appendChild(option);
  }
}

function salesSortValue(item) {
  const match = String(item.companyName || item.salesNumber || "").match(/^\s*(\d+)/);
  const number = match ? Number.parseInt(match[1], 10) : Number.NaN;
  return Number.isFinite(number) ? number : Number.MAX_SAFE_INTEGER;
}

function sortSalesPeople(items) {
  return [...items].sort((a, b) => {
    const numberDiff = salesSortValue(a) - salesSortValue(b);
    if (numberDiff !== 0) return numberDiff;
    return String(a.companyName || a.salesNumber || "").localeCompare(
      String(b.companyName || b.salesNumber || ""),
      undefined,
      { numeric: true }
    );
  });
}

function setDefaultLookups() {
  el("shipVia").value = state.lookups.orderTypes[0]?.shipDescription || "";
  el("salesOne").value = "";
}

function showDialog(dialogId = null) {
  ["routeMenu", "orderLookupPanel", "storePanel"].forEach((id) => {
    el(id).classList.toggle("is-hidden", id !== dialogId);
  });
}

function showOrderDetails() {
  document.body.classList.remove("order-details-collapsed");
  const tableShell = el("lineTableShell");
  if (tableShell) {
    tableShell.scrollTop = 0;
  }
}

function hideOrderDetails() {
  document.body.classList.add("order-details-collapsed");
}

function handleLineTableWheel(event) {
  const tableShell = el("lineTableShell");
  if (!tableShell) return;

  if (event.deltaY > 0) {
    const wasExpanded = !document.body.classList.contains("order-details-collapsed");
    hideOrderDetails();
    if (wasExpanded) {
      window.requestAnimationFrame(() => {
        tableShell.scrollTop += Math.max(48, Math.abs(event.deltaY));
      });
    }
    return;
  }

  if (event.deltaY < 0 && tableShell.scrollTop <= 0) {
    showOrderDetails();
  }
}

function setPageTitle(title) {
  el("pageTitle").textContent = title;
}

function setFormReadOnly(readOnly) {
  const locked = Boolean(readOnly);
  [
    "customerSearch",
    "customerButton",
    "shipDate",
    "poNumber",
    "refNumber",
    "attention",
    "shipVia",
    "salesOne",
    "storeButton",
    "scanInput",
    "scanButton",
    "discount",
    "discountAmount",
    "handling",
    "saveTestButton",
  ].forEach((id) => {
    const target = el(id);
    if (!target) return;
    target.disabled = locked;
  });
  renderLines();
  applyWriteMode();
}

function applyWriteMode() {
  const button = el("saveTestButton");
  if (!button) return;
  if (!state.writeEnabled) {
    button.disabled = true;
    button.textContent = "Read Only";
  }
}

function setWorkflowBusy(kind, busy) {
  state.busy[kind] = busy;
  const anyBusy = state.busy.lookup || state.busy.save || state.busy.print;
  ["orderLookupButton", "saveTestButton", "printInvoiceButton", "printPickListButton"].forEach((id) => {
    const target = el(id);
    if (!target) return;
    if (id === "saveTestButton" && state.mode === "list") {
      target.disabled = true;
      return;
    }
    if (id === "saveTestButton" && !state.writeEnabled) {
      target.disabled = true;
      return;
    }
    target.disabled = anyBusy;
  });
}

function showRouteMenu() {
  state.mode = "home";
  setPageTitle("Sales Order Processing");
  setOrderLookupHint("");
  showOrderDetails();
  clearOrderForm();
  setFormReadOnly(true);
  el("saveTestButton").textContent = "Save";
  showDialog("routeMenu");
}

function showOrderLookup(mode) {
  state.mode = mode;
  setPageTitle("Sales Order Processing");
  el("lookupTitle").textContent = mode === "list" ? "List Sales Order" : "Edit Sales Order";
  el("orderLookupButton").textContent = mode === "list" ? "List" : "Edit";
  el("orderLookupNumber").value = "";
  setOrderLookupHint("");
  showDialog("orderLookupPanel");
  el("orderLookupNumber").focus();
}

async function initialize() {
  el("orderDate").value = todayIso();
  el("shipDate").value = todayIso();

  try {
    const db = await api("/health/db");
    state.writeEnabled = Boolean(db.writeEnabled);
    el("connectionStatus").textContent = `${db.database.server_name} / ${db.database.database_name}`;
  } catch (error) {
    el("connectionStatus").textContent = "backend offline";
    setOrderLookupHint(`Backend is not ready: ${error.message}`, true);
    return;
  }

  const [orderTypes, sales] = await Promise.all([
    api("/api/lookups/order-types?limit=120"),
    api("/api/lookups/sales?limit=300"),
  ]);

  state.lookups.orderTypes = orderTypes;
  state.lookups.sales = sales;

  fillSelect(el("shipVia"), orderTypes, "shipDescription", "shipDescription", "");
  fillSelect(el("salesOne"), state.lookups.sales, "salesNumber", "companyName", " ");
  setDefaultLookups();

  if (await applyLaunchParams()) {
    return;
  }
  showRouteMenu();
}

async function applyLaunchParams() {
  const params = new URLSearchParams(window.location.search);
  const mode = (params.get("mode") || "").toLowerCase();
  const soNumber = Number(params.get("so") || 0);
  if (mode !== "list" || !soNumber) return false;

  try {
    state.mode = "list";
    showDialog(null);
    showOrderDetails();
    setFormReadOnly(true);
    setStatus(`Loading S/O ${soNumber}...`);
    const order = await api(`${OMS_ORDER_PATH}/${encodeURIComponent(soNumber)}`);
    loadOrderIntoForm(order, "list");
    return true;
  } catch (error) {
    showRouteMenu();
    setStatus(`Unable to list S/O ${soNumber}: ${error.message}`, true);
    return true;
  }
}

async function startAddOrder() {
  state.mode = "add";
  clearOrderForm();
  showOrderDetails();
  setPageTitle("Adding a Sales Order");
  showDialog(null);
  setFormReadOnly(false);
  el("saveTestButton").textContent = "Save Order";
  applyWriteMode();
  setStatus(
    state.writeEnabled
      ? "Ready. S/O number will be assigned when you save."
      : "Read-only production mode. Save is disabled."
  );
  el("customerSearch").focus();
}

function clearOrderForm() {
  showOrderDetails();
  state.customer = null;
  state.customerStores = [];
  state.selectedStoreIndex = -1;
  state.lines = [];
  state.discountMode = "percent";
  el("soNumber").value = "Draft";
  el("orderDate").value = todayIso();
  el("shipDate").value = todayIso();
  [
    "poNumber",
    "refNumber",
    "customerSearch",
    "terms",
    "termsDays",
    "cod",
    "attention",
    "billName",
    "billAddress",
    "billCity",
    "billState",
    "billZip",
    "email",
    "shipName",
    "shipAddress",
    "shipCity",
    "shipState",
    "shipZip",
    "phone",
    "storeNumber",
  ].forEach((id) => {
    el(id).value = "";
  });
  setDefaultLookups();
  el("discount").value = "0.00";
  el("handling").value = "0.00";
  setCustomerHint("");
  renderLines();
  updatePreview();
}

function setCustomer(customer) {
  state.customer = customer;
  el("customerSearch").value = customer.customerId || "";
  el("billName").value = customer.customerName || "";
  el("billAddress").value = customer.billAddress || "";
  el("billCity").value = customer.billCity || "";
  el("billState").value = customer.billState || "";
  el("billZip").value = customer.billZip || "";
  applyDefaultShipTo(customer);
  el("terms").value = customer.termDescription || "";
  el("termsDays").value = customer.termsDay ?? "";
  el("cod").value = customer.termsCod || "";
  el("attention").value = customer.attention || "";
  el("email").value = customer.email || "";

  if (customer.shipDescription) {
    const match = state.lookups.orderTypes.find((item) => item.shipDescription === customer.shipDescription);
    if (match) {
      el("shipVia").value = customer.shipDescription;
    }
  }

  if (customer.salesNumber) {
    el("salesOne").value = customer.salesNumber;
  }

  setStatus(`Loaded customer ${customer.customerId} ${customer.customerName || ""}.`);
  setCustomerHint("");
}

async function searchCustomer() {
  const q = el("customerSearch").value.trim();
  if (q.length < 2) {
    setCustomerHint("");
    setStatus("Enter a phone number or customer number first.", true);
    return false;
  }

  if (state.customerLookup.pending && state.customerLookup.lastQuery === q) {
    return state.customerLookup.pending;
  }

  state.customerLookup.lastQuery = q;
  setCustomerHint("Searching...");

  state.customerLookup.pending = (async () => {
    try {
      const matches = await api(`/api/customers/search?q=${encodeURIComponent(q)}&limit=10`);
      const list = Array.isArray(matches) ? matches : matches.value || [];
      if (!list.length) {
        state.customerLookup.lastSuccessQuery = "";
        setCustomerHint("No matching number.", true);
        setStatus("No customer found.", true);
        return false;
      }

      const selected = list[0];
      const customer = await api(`/api/customers/${encodeURIComponent(selected.customerId)}`);
      state.customerLookup.lastSuccessQuery = q;
      setCustomer(customer);
      const stores = await loadCustomerStores(customer.customerId);
      if (stores.length > 1) {
        setStatus(`Loaded customer ${customer.customerId}. Choose a store for Ship To.`);
      }
      updatePreview();
      return true;
    } catch (error) {
      setCustomerHint("Search failed.", true);
      setStatus(`Customer search failed: ${error.message}`, true);
      return false;
    } finally {
      state.customerLookup.pending = null;
    }
  })();

  return state.customerLookup.pending;
}

function searchCustomerOnExit() {
  const q = el("customerSearch").value.trim();
  if (q.length < 2 || state.mode === "list") return;
  if (q === state.customer?.customerId || q === state.customerLookup.lastSuccessQuery) return;
  searchCustomer();
}

function clearCustomerHintOnEdit() {
  const q = el("customerSearch").value.trim();
  if (!q || q !== state.customerLookup.lastQuery) {
    setCustomerHint("");
  }
}

function selectedWarehouse() {
  return "1";
}

function currentCustomerType() {
  const value = Number(state.customer?.customerType);
  return Number.isFinite(value) ? value : null;
}

function productLookupPath(code) {
  const params = new URLSearchParams();
  const customerType = currentCustomerType();
  if (customerType !== null) {
    params.set("customerType", String(customerType));
  }
  const query = params.toString();
  return `/api/products/lookup/${encodeURIComponent(code)}${query ? `?${query}` : ""}`;
}

function hasCustomerShipping(customer) {
  return Boolean(
    customer.shipCustomerName ||
      customer.shipAddress ||
      customer.shipCity ||
      customer.shipState ||
      customer.shipZip
  );
}

function applyDefaultShipTo(customer) {
  const useShipping = hasCustomerShipping(customer);
  el("shipName").value = useShipping
    ? customer.shipCustomerName || customer.customerName || ""
    : customer.customerName || "";
  el("shipAddress").value = useShipping
    ? customer.shipAddress || customer.billAddress || ""
    : customer.billAddress || "";
  el("shipCity").value = useShipping ? customer.shipCity || customer.billCity || "" : customer.billCity || "";
  el("shipState").value = useShipping ? customer.shipState || customer.billState || "" : customer.billState || "";
  el("shipZip").value = useShipping ? customer.shipZip || customer.billZip || "" : customer.billZip || "";
  el("phone").value = useShipping ? customer.shipPhone || customer.phone || "" : customer.phone || "";
}

function applyStoreShipTo(store) {
  el("storeNumber").value = store.storeNumber || "";
  el("shipName").value = store.storeName || "";
  el("shipAddress").value = store.address || "";
  el("shipCity").value = store.city || "";
  el("shipState").value = store.state || "";
  el("shipZip").value = store.zip || "";
  el("phone").value = store.phone || state.customer?.phone || "";
  state.selectedStoreIndex = state.customerStores.findIndex((item) => item.storeNumber === store.storeNumber);
}

async function loadCustomerStores(customerId) {
  state.customerStores = [];
  state.selectedStoreIndex = -1;
  el("storeNumber").value = "";
  if (!customerId) return [];
  const stores = await api(`/api/customers/${encodeURIComponent(customerId)}/stores`);
  state.customerStores = stores;
  return stores;
}

function renderStoreRows() {
  const body = el("storeBody");
  body.innerHTML = "";
  if (!state.customerStores.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="7">No chain stores for this customer.</td>';
    body.appendChild(row);
    return;
  }
  state.customerStores.forEach((store, index) => {
    const row = document.createElement("tr");
    row.dataset.index = String(index);
    row.classList.toggle("is-selected", index === state.selectedStoreIndex);
    row.innerHTML = `
      <td title="${store.storeName || ""}">${store.storeName || ""}</td>
      <td title="${store.storeNumber || ""}">${store.storeNumber || ""}</td>
      <td title="${store.address || ""}">${store.address || ""}</td>
      <td title="${store.city || ""}">${store.city || ""}</td>
      <td title="${store.state || ""}">${store.state || ""}</td>
      <td title="${store.zip || ""}">${store.zip || ""}</td>
      <td title="${store.phone || ""}">${store.phone || ""}</td>
    `;
    body.appendChild(row);
  });
}

async function openStorePanel() {
  if (!state.customer?.customerId) {
    setStatus("Load a customer before choosing a store.", true);
    return;
  }
  try {
    if (!state.customerStores.length) {
      await loadCustomerStores(state.customer.customerId);
    }
    const currentStoreNumber = el("storeNumber").value;
    if (currentStoreNumber) {
      state.selectedStoreIndex = state.customerStores.findIndex((store) => store.storeNumber === currentStoreNumber);
    }
    el("storeCustomerId").value = state.customer.customerId;
    renderStoreRows();
    showDialog("storePanel");
  } catch (error) {
    setStatus(`Store lookup failed: ${error.message}`, true);
  }
}

function chooseSelectedStore() {
  const store = state.customerStores[state.selectedStoreIndex];
  if (!store) {
    setStatus("Select a chain store first.", true);
    return;
  }
  applyStoreShipTo(store);
  showDialog(null);
  setStatus(`Selected store ${store.storeNumber || ""} ${store.storeName || ""}.`);
}

function availableForWarehouse(product) {
  const wh = selectedWarehouse();
  return (product.inventory || [])
    .filter((row) => String(row.warehouseNumber) === String(wh))
    .reduce((sum, row) => sum + Number(row.availableQty || 0), 0);
}

function isNegativeW1Line(line) {
  return Number(line?.available ?? 0) < 0;
}

function qtyText(value) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(2)));
}

function detailChip(title, value, options = {}) {
  const alertClass = options.alert ? " is-alert" : "";
  return `
    <div class="detail-chip${alertClass}">
      <div class="detail-chip-title">${escapeHtml(title)}</div>
      <div class="detail-chip-value">${escapeHtml(value)}</div>
    </div>
  `;
}

function inventoryRow(product, warehouseNumber) {
  return (product.inventory || []).find((row) => String(row.warehouseNumber).trim() === String(warehouseNumber));
}

function showProductDetailLoading(productCode) {
  el("detailItemCode").textContent = productCode || "";
  el("detailDescription").textContent = "Loading...";
  el("detailPrices").innerHTML = "";
  el("detailQty").innerHTML = "";
  el("detailLocation").innerHTML = "";
  el("productDetailImage").removeAttribute("src");
  el("productDetailImage").classList.add("is-hidden");
  el("productDetailNoImage").classList.remove("is-hidden");
  el("productDetailPanel").classList.remove("is-hidden");
}

function closeProductDetail() {
  el("productDetailPanel").classList.add("is-hidden");
}

function showScanFail(code, message) {
  el("scanFailMessage").textContent = `${code || "Scanned barcode"} was not found. ${message || ""}`.trim();
  el("scanFailPanel").classList.remove("is-hidden");
}

function closeScanFailAndManualEntry() {
  el("scanFailPanel").classList.add("is-hidden");
  el("scanInput").value = "";
  el("scanInput").focus();
}

function renderProductDetail(product) {
  const w1 = inventoryRow(product, "1");
  const w2 = inventoryRow(product, "2");
  const w6 = inventoryRow(product, "6");
  const totalQty = product.inventorySummary?.totalAvailable ?? [w1, w2, w6].reduce(
    (sum, row) => sum + Number(row?.availableQty || 0),
    0
  );
  const warehouseLocation = w1?.inventoryLocation || "";
  const showroomLocation = product.showroomLocation || "";
  const image = el("productDetailImage");
  const noImage = el("productDetailNoImage");

  el("detailItemCode").textContent = product.productCode || "--";
  el("detailDescription").textContent = product.description || "--";
  el("detailPrices").innerHTML = (product.priceLevels || []).map((level) => {
    const price = Number(level.price || 0);
    const label = String(level.label || "").replace(/^Level\s*/i, "L");
    return detailChip(label, price ? money(price) : "--");
  }).join("");
  el("detailQty").innerHTML = [
    detailChip("W1", qtyText(w1?.availableQty), { alert: Number(w1?.availableQty || 0) < 0 }),
    detailChip("W2", qtyText(w2?.availableQty)),
    detailChip("W6", qtyText(w6?.availableQty)),
    detailChip("Total Qty", qtyText(totalQty), { alert: Number(totalQty || 0) <= 0 }),
  ].join("");
  el("detailLocation").innerHTML = [
    detailChip("Warehouse", warehouseLocation || "--"),
    detailChip("Showroom", showroomLocation || "--"),
  ].join("");

  image.onload = () => {
    noImage.classList.add("is-hidden");
    image.classList.remove("is-hidden");
  };
  image.onerror = () => {
    image.classList.add("is-hidden");
    noImage.classList.remove("is-hidden");
  };
  image.src = `${API_BASE}${product.imageUrl || `/api/products/${encodeURIComponent(product.productCode || "")}/image`}`;
}

async function showProductDetail(productCode) {
  if (!productCode) return;
  showProductDetailLoading(productCode);
  try {
    const product = await api(productLookupPath(productCode));
    renderProductDetail(product);
  } catch (error) {
    el("detailDescription").textContent = `Product detail failed: ${error.message}`;
  }
}

function customerInfoCell(label, value, className = "") {
  return `
    <div class="customer-info-cell ${className}">
      <div class="customer-info-label">${escapeHtml(label)}</div>
      <div class="customer-info-value" title="${escapeHtml(value || "")}">${escapeHtml(value || "--")}</div>
    </div>
  `;
}

function renderCustomerDetailInfo(customer) {
  const billAddress = [customer.billAddress, customer.billAddress2, customer.billCity, customer.billState, customer.billZip]
    .filter(Boolean)
    .join(" ");
  const shipAddress = [customer.shipAddress, customer.shipAddress2, customer.shipCity, customer.shipState, customer.shipZip]
    .filter(Boolean)
    .join(" ");
  el("customerDetailInfo").innerHTML = [
    customerInfoCell("Customer #", customer.customerId),
    customerInfoCell("Name", customer.customerName, "customer-info-wide"),
    customerInfoCell("Type", customer.customerType),
    customerInfoCell("Sales", customer.salesNumber),
    customerInfoCell("Phone", customer.phone),
    customerInfoCell("Email", customer.email, "customer-info-wide"),
    customerInfoCell("Terms", customer.termDescription),
    customerInfoCell("COD", customer.termsCod),
    customerInfoCell("Bill To", billAddress, "customer-info-wide"),
    customerInfoCell("Ship To", shipAddress || billAddress, "customer-info-wide"),
    customerInfoCell("Attn", customer.attention, "customer-info-wide"),
    customerInfoCell("Tax Rate", customer.taxRate),
  ].join("");
}

function renderCustomerPurchases(purchases) {
  const body = el("customerPurchaseBody");
  if (!purchases.length) {
    body.innerHTML = '<tr><td colspan="6">No purchased products found.</td></tr>';
    return;
  }
  body.innerHTML = purchases.map((row) => `
    <tr>
      <td title="${escapeHtml(row.productCode || "")}">${escapeHtml(row.productCode || "")}</td>
      <td title="${escapeHtml(row.description || "")}">${escapeHtml(row.description || "")}</td>
      <td class="number">${money(row.unitPrice)}</td>
      <td class="number">${qtyDisplay(row.quantity)} ${escapeHtml(row.unitName || "")}</td>
      <td>${escapeHtml(row.soNumber || "")}</td>
      <td>${escapeHtml(row.orderDate || "")}</td>
    </tr>
  `).join("");
}

function renderCustomerOrders(orders) {
  const body = el("customerOrderBody");
  if (!orders.length) {
    body.innerHTML = '<tr><td colspan="7">No orders found.</td></tr>';
    return;
  }
  body.innerHTML = orders.map((row) => `
    <tr>
      <td>${escapeHtml(row.soNumber || "")}</td>
      <td>${escapeHtml(row.orderDate || "")}</td>
      <td class="number">${escapeHtml(row.itemCount || 0)}</td>
      <td class="number">${money(row.orderAmount)}</td>
      <td title="${escapeHtml(row.poNumber || "")}">${escapeHtml(row.poNumber || "")}</td>
      <td title="${escapeHtml(row.shipVia || "")}">${escapeHtml(row.shipVia || "")}</td>
      <td><button class="open-order" type="button" data-so-number="${escapeHtml(row.soNumber || "")}">List</button></td>
    </tr>
  `).join("");
}

function showCustomerDetailLoading() {
  el("customerDetailInfo").innerHTML = customerInfoCell("Loading", "Customer detail...");
  el("customerPurchaseBody").innerHTML = '<tr><td colspan="6">Loading...</td></tr>';
  el("customerOrderBody").innerHTML = '<tr><td colspan="7">Loading...</td></tr>';
  el("customerDetailPanel").classList.remove("is-hidden");
}

function closeCustomerDetail() {
  el("customerDetailPanel").classList.add("is-hidden");
}

async function openCustomerDetail() {
  if (!state.customer?.customerId) {
    const loaded = await searchCustomer();
    if (!loaded || !state.customer?.customerId) {
      setStatus("Load a customer before opening detail.", true);
      return;
    }
  }

  const customerId = state.customer.customerId;
  showCustomerDetailLoading();
  try {
    const [customer, orders, purchases] = await Promise.all([
      api(`/api/customers/${encodeURIComponent(customerId)}`),
      api(`/api/customers/${encodeURIComponent(customerId)}/orders?limit=1000`),
      api(`/api/customers/${encodeURIComponent(customerId)}/purchases?limit=1000`),
    ]);
    state.customerDetail.customer = customer;
    state.customerDetail.orders = orders;
    state.customerDetail.purchases = purchases;
    renderCustomerDetailInfo(customer);
    renderCustomerPurchases(purchases);
    renderCustomerOrders(orders);
    el("customerProductSearch").value = "";
  } catch (error) {
    el("customerDetailInfo").innerHTML = customerInfoCell("Error", error.message);
    el("customerPurchaseBody").innerHTML = '<tr><td colspan="6">Unable to load.</td></tr>';
    el("customerOrderBody").innerHTML = '<tr><td colspan="7">Unable to load.</td></tr>';
  }
}

async function searchCustomerPurchasedProducts() {
  const customerId = state.customerDetail.customer?.customerId || state.customer?.customerId;
  if (!customerId) return;
  const q = el("customerProductSearch").value.trim();
  el("customerPurchaseBody").innerHTML = '<tr><td colspan="6">Searching...</td></tr>';
  try {
    const purchases = await api(
      `/api/customers/${encodeURIComponent(customerId)}/purchases?q=${encodeURIComponent(q)}&limit=1000`
    );
    state.customerDetail.purchases = purchases;
    renderCustomerPurchases(purchases);
  } catch (error) {
    el("customerPurchaseBody").innerHTML = `<tr><td colspan="6">Search failed: ${escapeHtml(error.message)}</td></tr>`;
  }
}

function openOrderListWindow(soNumber) {
  const number = Number(soNumber || 0);
  if (!number) return;
  const url = new URL(window.location.href);
  url.searchParams.set("mode", "list");
  url.searchParams.set("so", String(number));
  const opened = window.open(url.toString(), "_blank");
  if (opened) {
    opened.opener = null;
  } else {
    setStatus("Browser blocked the order list window. Allow pop-ups for this site.", true);
  }
}

async function addScannedProduct() {
  const code = el("scanInput").value.trim();
  if (!code) {
    setStatus("Scan or enter an item number first.", true);
    return;
  }

  try {
    const product = await api(productLookupPath(code));
    const existing = state.lines.find((line) => line.productCode === product.productCode);
    if (existing) {
      existing.quantity += 1;
      existing.extAmount = existing.quantity * existing.unitPrice;
      setStatus(`Added 1 more ${product.productCode}.`);
    } else {
      const price = Number(product.unitPrice ?? product.wholesalePrice2 ?? product.wholesalePrice ?? product.retailPrice ?? 0);
      const line = {
        productCode: product.productCode,
        description: product.description || "",
        warehouse: selectedWarehouse(),
        pack: product.piecesPerCase || "",
        taxInd: product.taxInd || "N",
        quantity: 1,
        unitName: product.unitName || "PC",
        shippedQty: 0,
        unitPrice: price,
        extAmount: price,
        available: availableForWarehouse(product),
        shipDate: el("shipDate").value,
      };
      state.lines.push(line);
      setStatus(`Added ${product.productCode} ${product.description || ""}.`);
    }
    el("scanInput").value = "";
    renderLines();
    updatePreview();
    el("scanInput").focus();
  } catch (error) {
    setStatus(`Product lookup failed: ${error.message}`, true);
    el("scanInput").value = "";
    showScanFail(code, error.message);
  }
}

function renderLines() {
  const body = el("lineBody");
  body.innerHTML = "";

  if (!state.lines.length) {
    const row = document.createElement("tr");
    row.className = "empty-row";
    row.innerHTML = '<td colspan="9">Scan a product to start the order.</td>';
    body.appendChild(row);
    return;
  }

  const readOnly = state.mode === "list";
  state.lines.forEach((line, index) => {
    const row = document.createElement("tr");
    row.dataset.index = String(index);
    row.classList.toggle("is-negative-w1", isNegativeW1Line(line));
    const disabled = readOnly ? "disabled" : "";
    const productCode = escapeHtml(line.productCode);
    const description = escapeHtml(line.description);
    const unitName = escapeHtml(line.unitName || "");
    row.innerHTML = `
      <td>${index + 1}</td>
      <td class="item-detail-cell" title="${productCode}" data-product-code="${productCode}">${productCode}</td>
      <td title="${description}"><input class="editable line-description" data-index="${index}" type="text" maxlength="60" value="${description}" ${disabled} /></td>
      <td class="number">${line.pack || ""}</td>
      <td><input class="editable line-qty" data-index="${index}" type="number" min="0.001" step="1" value="${line.quantity}" ${disabled} /></td>
      <td>${unitName}</td>
      <td><input class="editable line-price" data-index="${index}" type="number" min="0" step="0.0001" value="${line.unitPrice}" ${disabled} /></td>
      <td class="number">${money(line.extAmount)}</td>
      <td>${readOnly ? "" : `<button class="remove-line" data-index="${index}">Del</button>`}</td>
    `;
    body.appendChild(row);
  });
}

function syncLineFromInput(event) {
  if (state.mode === "list") return;
  const target = event.target;
  const index = Number(target.dataset.index);
  const line = state.lines[index];
  if (!line) return;

  if (target.classList.contains("line-qty")) {
    line.quantity = Number(target.value || 0);
  }
  if (target.classList.contains("line-price")) {
    line.unitPrice = Number(target.value || 0);
  }
  if (target.classList.contains("line-description")) {
    line.description = target.value.slice(0, 60);
    target.value = line.description;
    target.title = line.description;
    return;
  }
  line.extAmount = line.quantity * line.unitPrice;
  renderLines();
  updatePreview();
}

async function updatePreview() {
  const seq = ++state.previewSeq;
  const subtotal = state.lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unitPrice || 0), 0);
  let discountRate = Number(el("discount").value || 0);
  let discountAmount = Number(el("discountAmount").value || 0);
  if (state.discountMode === "amount") {
    discountAmount = Math.min(Math.max(discountAmount, 0), subtotal);
    discountRate = subtotal ? (discountAmount * 100) / subtotal : 0;
    if (!isEditingField("discount")) {
      el("discount").value = Number(discountRate.toFixed(6)).toString();
    }
  } else {
    discountRate = Math.max(discountRate, 0);
    discountAmount = subtotal * discountRate / 100;
    if (!isEditingField("discountAmount")) {
      el("discountAmount").value = money(discountAmount);
    }
  }
  const payload = {
    lines: state.lines.map((line) => ({
      productCode: line.productCode,
      description: line.description,
      quantity: line.quantity,
      unitPrice: line.unitPrice,
      taxInd: line.taxInd,
    })),
    discount: discountRate,
    discountAmount: state.discountMode === "amount" ? discountAmount : null,
    handling: Number(el("handling").value || 0),
    taxRate: Number(state.customer?.taxRate || 0),
  };

  if (!payload.lines.length) {
    el("subtotal").value = "0.00";
    if (!isEditingField("discountAmount")) {
      el("discountAmount").value = "0.00";
    }
    el("tax").value = "0.00";
    el("total").value = "0.00";
    el("balance").value = "0.00";
    return;
  }

  try {
    const preview = await api("/api/orders/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (seq !== state.previewSeq) return;
    el("subtotal").value = money(preview.subtotal);
    if (!isEditingField("discountAmount")) {
      el("discountAmount").value = money(preview.discountAmount);
    }
    if (!isEditingField("discount")) {
      el("discount").value = Number(preview.discountRate).toString();
    }
    el("tax").value = money(preview.tax);
    el("total").value = money(preview.total);
    el("balance").value = money(preview.total);
  } catch (error) {
    setStatus(`Preview failed: ${error.message}`, true);
  }
}

function clearLines() {
  if (state.mode === "list") return;
  state.lines = [];
  renderLines();
  updatePreview();
  setStatus("Lines cleared.");
}

function buildDraftPayload() {
  return {
    customer: state.customer,
    header: {
      soNumber: Number(el("soNumber").value || 0) || null,
      customerId: state.customer?.customerId || el("customerSearch").value.trim() || null,
      customerName: el("billName").value || null,
      phone: el("phone").value || null,
      orderDate: el("orderDate").value,
      shipDate: el("shipDate").value || null,
      orderType: null,
      shipVia: el("shipVia").value,
      salesOne: el("salesOne").value,
      salesTwo: null,
      warehouse: selectedWarehouse(),
      storeNumber: el("storeNumber").value,
      poNumber: el("poNumber").value,
      refNumber: el("refNumber").value,
      attention: valueOf("attention"),
      billName: el("billName").value,
      billAddress: el("billAddress").value,
      billCity: el("billCity").value,
      billState: el("billState").value,
      billZip: el("billZip").value,
      shipName: el("shipName").value,
      shipAddress: el("shipAddress").value,
      shipCity: el("shipCity").value,
      shipState: el("shipState").value,
      shipZip: el("shipZip").value,
      terms: el("terms").value,
      termsDays: Number(el("termsDays").value || 0),
      termsCod: el("cod").value,
      email: el("email").value,
    },
    lines: state.lines.map((line) => ({
      lineId: line.lineId || null,
      lineNumber: line.lineNumber || null,
      commLine: line.commLine || null,
      productCode: line.productCode,
      description: line.description,
      warehouse: line.warehouse || selectedWarehouse(),
      pack: Number(line.pack || 0),
      taxInd: line.taxInd || "N",
      quantity: Number(line.quantity || 0),
      unitName: line.unitName,
      shippedQty: Number(line.shippedQty || 0),
      unitPrice: Number(line.unitPrice || 0),
      available: Number(line.available || 0),
      shipDate: line.shipDate || el("shipDate").value || null,
    })),
    totals: {
      subtotal: Number(el("subtotal").value || 0),
      taxableAmount: Number(el("tax").value || 0) > 0 ? Number(el("subtotal").value || 0) - Number(el("discountAmount").value || 0) : 0,
      taxRate: Number(state.customer?.taxRate || 0),
      tax: Number(el("tax").value || 0),
      discount: Number(el("discount").value || 0),
      handling: Number(el("handling").value || 0),
      total: Number(el("total").value || 0),
    },
  };
}

function loadOrderIntoForm(order, mode) {
  showOrderDetails();
  const header = order.header || {};
  state.mode = mode;
  state.customer = {
    customerId: header.customerId || "",
    customerName: header.customerName || header.billName || "",
    taxRate: Number(header.taxRate || 0),
    customerType: header.customerType ?? null,
  };
  state.lines = (order.lines || []).map((line) => ({
    lineId: line.lineId || null,
    lineNumber: line.lineNumber || null,
    commLine: line.commLine || null,
    productCode: line.productCode,
    description: line.description || "",
    warehouse: line.warehouse || selectedWarehouse(),
    pack: line.pack || "",
    taxInd: line.taxInd || "N",
    quantity: Number(line.quantity || 0),
    unitName: line.unitName || "PC",
    shippedQty: Number(line.shippedQty || 0),
    unitPrice: Number(line.unitPrice || 0),
    extAmount: Number(line.extAmount || 0),
    available: Number(line.available || 0),
    shipDate: line.shipDate || header.shipDate || todayIso(),
  }));

  el("soNumber").value = header.soNumber || "";
  el("orderDate").value = header.orderDate || todayIso();
  el("shipDate").value = header.shipDate || header.orderDate || todayIso();
  el("poNumber").value = header.poNumber || "";
  el("refNumber").value = header.refNumber || "";
  el("customerSearch").value = header.customerId || "";
  el("terms").value = header.terms || "";
  el("termsDays").value = header.termsDays ?? "";
  el("cod").value = header.termsCod || "";
  el("attention").value = header.attention || "";
  el("billName").value = header.billName || header.customerName || "";
  el("billAddress").value = header.billAddress || "";
  el("billCity").value = header.billCity || "";
  el("billState").value = header.billState || "";
  el("billZip").value = header.billZip || "";
  el("email").value = header.email || "";
  el("shipName").value = header.shipName || header.customerName || "";
  el("shipAddress").value = header.shipAddress || "";
  el("shipCity").value = header.shipCity || "";
  el("shipState").value = header.shipState || "";
  el("shipZip").value = header.shipZip || "";
  el("phone").value = header.phone || "";
  el("storeNumber").value = header.storeNumber || "";
  el("shipVia").value = header.shipVia || "";
  el("salesOne").value = header.salesOne || "";
  el("discount").value = Number(header.discount || 0);
  state.discountMode = "percent";
  el("handling").value = money(header.handling || 0);

  setPageTitle(mode === "list" ? `Sales Order ${header.soNumber}` : `Editing Sales Order ${header.soNumber}`);
  setFormReadOnly(mode === "list");
  el("saveTestButton").textContent = mode === "edit" ? "Update Order" : "List View Only";
  applyWriteMode();
  showDialog(null);
  renderLines();
  updatePreview();
  setStatus(mode === "list" ? `Listed S/O ${header.soNumber}.` : `Loaded S/O ${header.soNumber} for edit.`);
}

async function loadOrderFromLookup() {
  if (state.busy.lookup) return;
  const soNumber = Number(el("orderLookupNumber").value || 0);
  if (!soNumber) {
    setOrderLookupHint("Enter an S/O number.", true);
    return;
  }

  setWorkflowBusy("lookup", true);
  setOrderLookupHint("Loading...");
  try {
    const order = await api(`${OMS_ORDER_PATH}/${soNumber}`);
    loadOrderIntoForm(order, state.mode);
    setOrderLookupHint("");
  } catch (error) {
    setOrderLookupHint(error.message || "Order not found.", true);
  } finally {
    setWorkflowBusy("lookup", false);
  }
}

async function saveTestDatabase() {
  if (state.busy.save) return;
  if (state.mode === "list") return;
  if (!state.lines.length) {
    setStatus("Add at least one product before saving.", true);
    return;
  }

  const button = el("saveTestButton");
  setWorkflowBusy("save", true);
  button.textContent = state.mode === "edit" ? "Updating..." : "Saving...";

  try {
    await updatePreview();
    const payload = buildDraftPayload();
    const path = state.mode === "edit"
      ? `${OMS_ORDER_PATH}/${encodeURIComponent(payload.header.soNumber)}`
      : OMS_ORDER_PATH;
    const result = await api(path, {
      method: state.mode === "edit" ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    const order = result.order || {};
    el("soNumber").value = order.soNumber || payload.header.soNumber || "";
    showOrderDetails();
    const action = state.mode === "edit" ? "Updated" : "Saved";
    setStatus(`${action} S/O ${order.soNumber || payload.header.soNumber}.`);
    if (state.mode === "add") {
      state.mode = "edit";
      setPageTitle(`Editing Sales Order ${order.soNumber || payload.header.soNumber}`);
      el("saveTestButton").textContent = "Update Order";
    }
  } catch (error) {
    setStatus(`Save failed: ${error.message}`, true);
  } finally {
    setWorkflowBusy("save", false);
    button.textContent = state.mode === "edit" ? "Update Order" : "Save Order";
  }
}

function closePage() {
  if (state.mode === "add" || state.mode === "edit") {
    const confirmed = window.confirm("Return to the home menu in this window? Unsaved changes on this page will be lost.");
    if (!confirmed) return;
  }
  showRouteMenu();
}

function openHomeMenu() {
  if (state.mode === "add" || state.mode === "edit") {
    const opened = window.open(window.location.href, "_blank");
    if (opened) {
      opened.opener = null;
    } else {
      setStatus("Browser blocked the home menu window. Allow pop-ups for this site.", true);
    }
    return;
  }
  showRouteMenu();
}

async function openPrintPdf(kind) {
  if (state.busy.print || state.busy.save) return;
  const soNumber = Number(el("soNumber").value || 0);
  if (!soNumber) {
    setStatus("Save or load an order before printing.", true);
    return;
  }
  const label = kind === "invoice" ? "Customer Sales Order" : "Picking List";
  const confirmed = window.confirm(`Print ${label} for S/O ${soNumber}?`);
  if (!confirmed) return;
  setWorkflowBusy("print", true);
  try {
    const response = await fetch(`${API_BASE}${OMS_ORDER_PATH}/${encodeURIComponent(soNumber)}/print/${kind}`, {
      method: "POST",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload.detail || "No available printer. Please check server printers.";
      window.alert(message);
      setStatus(message, true);
      return;
    }
    setStatus(`${label} sent to ${payload.printer}.`);
  } catch (error) {
    const message = `Print failed: ${error.message}`;
    window.alert(message);
    setStatus(message, true);
  } finally {
    setWorkflowBusy("print", false);
  }
}

function runSelectedRoute() {
  const selected = document.querySelector('input[name="routeChoice"]:checked')?.value || "add";
  if (selected === "add") {
    startAddOrder();
    return;
  }
  showOrderLookup(selected);
}

document.addEventListener("DOMContentLoaded", () => {
  initialize();

  el("routeOk").addEventListener("click", runSelectedRoute);
  el("routeExit").addEventListener("click", showRouteMenu);
  el("routeExitTop").addEventListener("click", showRouteMenu);
  el("lookupBackButton").addEventListener("click", showRouteMenu);
  el("lookupCancelButton").addEventListener("click", showRouteMenu);
  el("orderLookupButton").addEventListener("click", loadOrderFromLookup);
  el("orderLookupNumber").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadOrderFromLookup();
  });
  el("storeButton").addEventListener("click", openStorePanel);
  el("storeCloseTop").addEventListener("click", () => showDialog(null));
  el("storeCloseButton").addEventListener("click", () => showDialog(null));
  el("storeSelectButton").addEventListener("click", chooseSelectedStore);
  el("productDetailClose").addEventListener("click", closeProductDetail);
  el("productDetailCloseBottom").addEventListener("click", closeProductDetail);
  el("productDetailPanel").addEventListener("click", (event) => {
    if (event.target.id === "productDetailPanel") {
      closeProductDetail();
    }
  });
  el("scanFailClose").addEventListener("click", closeScanFailAndManualEntry);
  el("scanFailPanel").addEventListener("click", (event) => {
    if (event.target.id === "scanFailPanel") {
      closeScanFailAndManualEntry();
    }
  });
  el("storeBody").addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    state.selectedStoreIndex = Number(row.dataset.index);
    renderStoreRows();
  });
  el("storeBody").addEventListener("dblclick", (event) => {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    state.selectedStoreIndex = Number(row.dataset.index);
    chooseSelectedStore();
  });

  el("customerButton").addEventListener("click", searchCustomer);
  el("customerDetailButton").addEventListener("click", openCustomerDetail);
  el("customerDetailClose").addEventListener("click", closeCustomerDetail);
  el("customerDetailCloseBottom").addEventListener("click", closeCustomerDetail);
  el("customerDetailPanel").addEventListener("click", (event) => {
    if (event.target.id === "customerDetailPanel") {
      closeCustomerDetail();
    }
  });
  el("customerProductSearchButton").addEventListener("click", searchCustomerPurchasedProducts);
  el("customerProductSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchCustomerPurchasedProducts();
  });
  el("customerOrderBody").addEventListener("click", (event) => {
    const button = event.target.closest(".open-order");
    if (!button) return;
    openOrderListWindow(button.dataset.soNumber);
  });
  el("customerSearch").addEventListener("blur", searchCustomerOnExit);
  el("customerSearch").addEventListener("input", clearCustomerHintOnEdit);
  el("customerSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchCustomer();
    if (event.key === "Tab") searchCustomerOnExit();
  });

  el("scanButton").addEventListener("click", addScannedProduct);
  el("scanInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === "Tab") {
      if (event.key === "Tab") event.preventDefault();
      addScannedProduct();
    }
  });

  el("lineTableShell").addEventListener("wheel", handleLineTableWheel, { passive: true });

  el("lineBody").addEventListener("input", (event) => {
    if (event.target.closest(".line-description")) {
      syncLineFromInput(event);
    }
  });
  el("lineBody").addEventListener("change", syncLineFromInput);
  el("lineBody").addEventListener("click", (event) => {
    const itemCell = event.target.closest(".item-detail-cell");
    if (itemCell) {
      showProductDetail(itemCell.dataset.productCode || "");
      return;
    }
    const button = event.target.closest(".remove-line");
    if (!button || state.mode === "list") return;
    state.lines.splice(Number(button.dataset.index), 1);
    renderLines();
    updatePreview();
  });

  el("discount").addEventListener("input", () => {
    state.discountMode = "percent";
    updatePreview();
  });
  el("discountAmount").addEventListener("input", () => {
    state.discountMode = "amount";
    updatePreview();
  });
  el("handling").addEventListener("input", updatePreview);
  ["discount", "discountAmount", "handling"].forEach((id) => {
    el(id).addEventListener("blur", () => normalizeEmptyZeroField(id));
  });
  el("menuButton").addEventListener("click", openHomeMenu);
  el("printInvoiceButton").addEventListener("click", () => openPrintPdf("invoice"));
  el("printPickListButton").addEventListener("click", () => openPrintPdf("picking-list"));
  el("saveTestButton").addEventListener("click", saveTestDatabase);
  el("closeButton").addEventListener("click", closePage);
});
