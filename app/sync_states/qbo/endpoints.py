ENDPOINTS = [
    'CompanyInfo', 'Preferences', 'Account', 'Customer', 'Vendor', 'Employee', 'TaxRate', 'TaxCode', 'Invoice',
    'Item', 'Deposit', 'CompanyCurrency', 'Payment', 'Bill', 'BillPayment', 'VendorCredit', 'CreditMemo'
]

SKIP_PAGINATION = ['CompanyInfo', 'Preferences']

SKIP_ID_IN_API_GET = ['CompanyInfo', 'Preferences']

TRANSACTIONAL_ENDPOINTS = [
    'Invoice', 'Deposit', 'Payment', 'Bill', 'BillPayment', 'VendorCredit', 'CreditMemo'
]

HAS_ACTIVE_FLAG = [
    'Account', 'Customer', 'Vendor', 'Employee', 'TaxRate', 'TaxCode', 'Item', 'CompanyCurrency'
]

# Below are the endpoints used to map ingested `Journal` report transaction types
ENDPOINT_TYPE_INVOICE = 'Invoice'
ENDPOINT_TYPE_PAYMENT = 'Payment'
ENDPOINT_TYPE_CREDIT_MEMO = 'CreditMemo'
ENDPOINT_TYPE_BILL = 'Bill'
ENDPOINT_TYPE_BILL_PAYMENT = 'BillPayment'
ENDPOINT_TYPE_VENDOR_CREDIT = 'VendorCredit'
ENDPOINT_TYPE_JOURNAL_ENTRY = 'JournalEntry'
ENDPOINT_TYPE_SALES_RECEIPT = 'SalesReceipt'
ENDPOINT_TYPE_REFUND_RECEIPT = 'RefundReceipt'
ENDPOINT_TYPE_PURCHASE = 'Purchase'
ENDPOINT_TYPE_PURCHASE_ORDER = 'PurchaseOrder'
ENDPOINT_TYPE_ESTIMATE = 'Estimate'
ENDPOINT_TYPE_DEPOSIT = 'Deposit'
ENDPOINT_TYPE_TRANSFER = 'Transfer'
ENDPOINT_TYPE_TIME_ACTIVITY = 'TimeActivity'

# Below are the endpoints used as placeholders for journal transaction types which don't have endpoints as they
# aren't publicly exposed in the QBO API
ENDPOINT_INVENTORY_DESKTOP_STARTING_VALUE ='InventoryDesktopStartingValue'
ENDPOINT_INVENTORY_STARTING_VALUE = 'InventoryStartingValue'
ENDPOINT_INVENTORY_QTY_ADJUST ='InventoryQtyAdjust'
ENDPOINT_TAX_PAYMENT = 'TaxPayment'
ENDPOINT_BILLABLE_CHARGE = 'BillableCharge'
ENDPOINT_CREDIT = 'Credit'
ENDPOINT_CHARGE = 'Charge'
ENDPOINT_GST_PAYMENT = 'GSTPayment'
ENDPOINT_STATEMENT = 'Statement'
ENDPOINT_PAYROLL_CHECK = 'PayrollCheck'
ENDPOINT_PAYROLL_ADJUSTMENT = 'PayrollAdjustment'
ENDPOINT_PAYROLL_REFUND = 'PayrollRefund'
ENDPOINT_GLOBAL_TAX_PAYMENT = 'GlobalTaxPayment'
ENDPOINT_GLOBAL_TAX_ADJUSTMENT = 'GlobalTaxAdjustment'
ENDPOINT_JOB = 'Job'
ENDPOINT_SERVICE_TAX_PARTIAL_UTILISATION = 'ServiceTaxPartialUtilisation'
ENDPOINT_SERVICE_TAX_DEFER = 'ServiceTaxDefer'
ENDPOINT_SERVICE_TAX_REVERSAL = 'ServiceTaxReversal'
ENDPOINT_SERVICE_TAX_REFUND = 'ServiceTaxRefund'
ENDPOINT_SERVICE_TAX_GROSS_ADJUSTMENT = 'ServiceTaxGrossAdjustment'
ENDPOINT_REVERSE_CHARGE = 'ReverseCharge'

# A dict used to map a `Journal` transaction type to its respective endpoint in QBO
JOURNAL_TXN_TYPE_TO_ENDPOINT_MAP = {
    'Invoice': ENDPOINT_TYPE_INVOICE,
    'Payment': ENDPOINT_TYPE_PAYMENT,
    'Adjustment Note': ENDPOINT_TYPE_CREDIT_MEMO,
    'Credit Memo': ENDPOINT_TYPE_CREDIT_MEMO,
    'Bill': ENDPOINT_TYPE_BILL,
    'Bill Payment (Check)': ENDPOINT_TYPE_BILL_PAYMENT,
    'Bill Payment (Cheque)': ENDPOINT_TYPE_BILL_PAYMENT,
    'Bill Payment (Credit Card)': ENDPOINT_TYPE_BILL_PAYMENT,
    'Supplier Credit': ENDPOINT_TYPE_VENDOR_CREDIT,
    'Vendor Credit': ENDPOINT_TYPE_VENDOR_CREDIT,
    'Journal Entry': ENDPOINT_TYPE_JOURNAL_ENTRY,
    'Receive Payment': ENDPOINT_TYPE_SALES_RECEIPT,
    'Advance Payment': ENDPOINT_TYPE_SALES_RECEIPT,
    'Sales Receipt': ENDPOINT_TYPE_SALES_RECEIPT,
    'Credit Refund': ENDPOINT_TYPE_REFUND_RECEIPT,
    'Refund': ENDPOINT_TYPE_REFUND_RECEIPT,
    'Cash Expense': ENDPOINT_TYPE_PURCHASE,
    'Cheque Expense': ENDPOINT_TYPE_PURCHASE,
    'Check': ENDPOINT_TYPE_PURCHASE,
    'Expense': ENDPOINT_TYPE_PURCHASE,
    'Credit Card Charge': ENDPOINT_TYPE_PURCHASE,
    'Credit Card Credit': ENDPOINT_TYPE_PURCHASE,
    'Cash Purchase': ENDPOINT_TYPE_PURCHASE,
    'Credit Purchase': ENDPOINT_TYPE_PURCHASE,
    'Purchase Order': ENDPOINT_TYPE_PURCHASE_ORDER,
    'Estimate': ENDPOINT_TYPE_ESTIMATE,
    'Deposit': ENDPOINT_TYPE_DEPOSIT,
    'Transfer': ENDPOINT_TYPE_TRANSFER,
    'Time Activity': ENDPOINT_TYPE_TIME_ACTIVITY,
    'Inventory Desktop Starting Value': ENDPOINT_INVENTORY_DESKTOP_STARTING_VALUE,
    'Inventory Starting Value': ENDPOINT_INVENTORY_STARTING_VALUE,
    'Inventory Qty Adjust': ENDPOINT_INVENTORY_QTY_ADJUST,
    'Tax Payment': ENDPOINT_TAX_PAYMENT,
    'Billable Charge': ENDPOINT_BILLABLE_CHARGE,
    'Credit': ENDPOINT_CREDIT,
    'Charge': ENDPOINT_CHARGE,
    'GST Payment': ENDPOINT_GST_PAYMENT,
    'Statement': ENDPOINT_STATEMENT,
    'Payroll Check': ENDPOINT_PAYROLL_CHECK,
    'Payroll Adjustment': ENDPOINT_PAYROLL_ADJUSTMENT,
    'Payroll Refund': ENDPOINT_PAYROLL_REFUND,
    'Global Tax Payment': ENDPOINT_GLOBAL_TAX_PAYMENT,
    'Global Tax Adjustment': ENDPOINT_GLOBAL_TAX_ADJUSTMENT,
    'Job': ENDPOINT_JOB,
    'Service Tax Partial Utilisation': ENDPOINT_SERVICE_TAX_PARTIAL_UTILISATION,
    'Service Tax Defer': ENDPOINT_SERVICE_TAX_DEFER,
    'Service Tax Reversal': ENDPOINT_SERVICE_TAX_REVERSAL,
    'Service Tax Refund': ENDPOINT_SERVICE_TAX_REFUND,
    'Service Tax Gross Adjustment': ENDPOINT_SERVICE_TAX_GROSS_ADJUSTMENT,
    'Reverse Charge': ENDPOINT_REVERSE_CHARGE
}
