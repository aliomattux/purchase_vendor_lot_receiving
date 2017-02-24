from openerp.osv import osv, fields


class PurchaseOrderLotView(osv.osv_memory):
    _name = 'purchase.order.lot.view'
    _columns = {
	'product': fields.many2one('product.product', 'Product'),
	'lines': fields.one2many('purchase.order.line.lot.view', 'parent', 'Details'),
    }

    def default_get(self, cr, uid, fields, context=None):
	print 'CALL'
	line_id = context.get('active_id')
	line = self.pool.get('purchase.order.line').browse(cr, uid, line_id)
	product_id = line.product_id.id
	po_id = line.order_id.id

	cr.execute("""SELECT line.product, lot.id AS lot, lot.state, line.product_qty AS quantity \
	FROM stock_vendor_lot lot \
	JOIN stock_vendor_lot_line line ON (lot.id = line.vendor_lot) \
	WHERE line.product = %s AND lot.purchase = %s""", (product_id, po_id))
	data = cr.dictfetchall()
	print data
	return {'product': product_id, 'lines': data}



class PurchaseOrderLineLotView(osv.osv_memory):
    _name = 'purchase.order.line.lot.view'
    _columns = {
	'parent': fields.many2one('purchase.order.lot.view', 'Parent'),
        'product': fields.many2one('product.product', 'Product'),
        'quantity': fields.float('Quantity'),
        'state': fields.selection([('draft', 'Draft'),
                        ('checkin', 'Ready to Count'),
                        ('verification', 'Pending Verification'),
                        ('exception', 'Exception'),
                        ('putaway', 'Pending Putaway'),
                        ('done', 'Done')
        ], 'State'),
        'lot': fields.many2one('stock.vendor.lot', 'License Plate'),
    }

