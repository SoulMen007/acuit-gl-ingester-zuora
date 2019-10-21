INVOICE = 'Invoice'
INVOICE_ITEM = 'InvoiceItem'
PRODUCT = 'Product'

ENDPOINTS = [
    INVOICE, INVOICE_ITEM, PRODUCT
]

ENDPOINT_QUERY_FIELDS = {
    INVOICE_ITEM: [
        "AccountingCode", "ChargeAmount", "ChargeDate", "ChargeName", "CreatedById", "CreatedDate",
        "Id", "InvoiceId", "ProcessingType", "ProductDescription", "ProductName", "Quantity",
        "RatePlanChargeId", "RevRecStartDate", "ServiceEndDate", "ServiceStartDate", "SKU",
        "SubscriptionId", "TaxAmount", "TaxCode", "TaxExemptAmount", "TaxMode", "UnitPrice", "UOM",
        "UpdatedById", "UpdatedDate"
    ],

    INVOICE: [
        'AccountId', 'AdjustmentAmount', 'Amount', 'AmountWithoutTax', 'Balance', 'Comments',
        'CreatedById', 'CreatedDate', 'CreditBalanceAdjustmentAmount', 'DueDate', 'Id', 'IncludesOneTime',
        'IncludesUsage', 'InvoiceDate', 'InvoiceNumber', 'LastEmailSentDate', 'PaymentAmount', 'PostedBy',
        'PostedDate', 'RefundAmount', 'Status', 'TargetDate', 'TaxAmount', 'TaxExemptAmount', 'TransferredToAccounting',
        'UpdatedById', 'UpdatedDate'
    ],

    PRODUCT: [
        'AllowFeatureChanges', 'Category', 'CreatedById', 'CreatedDate', 'Description', 'EffectiveEndDate',
        'EffectiveStartDate', 'Id', 'Name', 'SKU', 'UpdatedById', 'UpdatedDate',
    ]

}


